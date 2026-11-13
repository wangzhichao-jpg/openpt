# SPDX-License-Identifier: Apache-2.0
"""用模拟 GitHub API 验证草稿按 ID 恢复及写入失败不重试。"""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(ROOT / "releases"))
    spec = importlib.util.spec_from_file_location(
        "publisher_test", ROOT / "releases/publish_windows.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/project")
    manifest = {"source_sha": "a" * 40, "bundle": "demo.zip", "app": "app", "sha256": "b" * 64}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "demo.zip").write_bytes(b"zip")
    (tmp_path / "demo.zip.sha256").write_bytes(b"side")
    release = {
        "id": 15,
        "tag_name": mod.TAG,
        "name": mod.TITLE,
        "draft": True,
        "target_commitish": manifest["source_sha"],
        "prerelease": False,
    }
    calls = []
    assets = []
    candidates = [release]
    monkeypatch.setattr(mod, "validate", lambda *_: None)
    monkeypatch.setattr(
        mod, "sha256", lambda path: "d" * 64 if path.name == "demo.zip" else "e" * 64
    )

    def api(path):
        calls.append(("GET", path))
        if "/git/ref/" in path:
            return {"object": {"sha": manifest["source_sha"]}}
        assert "/releases/tags/" not in path, "按 tag 查草稿不可用"
        assert path.endswith("/releases/15")
        return release.copy()

    def pages(path):
        calls.append(("LIST", path))
        return list(assets if "/assets?" in path else candidates)

    def gh(*args):
        calls.append(("WRITE", *args))
        if "POST" in args:
            candidates.append(release)
            return json.dumps(release)
        if "PATCH" in args:
            release["draft"] = False
            return "{}"
        raise AssertionError(args)

    def upload(repo, release_id, file):
        calls.append(("UPLOAD", str(release_id), file.name))
        assets.append(
            {
                "name": file.name,
                "state": "uploaded",
                "size": file.stat().st_size,
                "digest": "sha256:" + mod.sha256(file),
            }
        )

    monkeypatch.setattr(mod, "api", api)
    monkeypatch.setattr(mod, "list_pages", pages)
    monkeypatch.setattr(mod, "gh", gh)
    monkeypatch.setattr(mod, "upload", upload)
    return mod, manifest_path, tmp_path, release, candidates, assets, calls


def test_existing_draft_is_reused_without_create(state):
    mod, manifest, directory, _, _, _, calls = state
    mod.main(manifest, directory)
    assert not any("POST" in call for call in calls)
    assert sum(call[0] == "UPLOAD" for call in calls) == 2
    assert any("PATCH" in call for call in calls)
    assert all("/releases/tags/" not in str(call) for call in calls)


def test_created_response_id_is_used_without_by_tag(state):
    mod, manifest, directory, _, candidates, _, calls = state
    candidates.clear()
    mod.main(manifest, directory)
    assert sum("POST" in call for call in calls) == 1
    assert any("/releases/15/assets?" in str(call) for call in calls)
    assert all("/releases/tags/" not in str(call) for call in calls)


def test_identical_assets_not_uploaded_twice(state):
    mod, manifest, directory, _, _, assets, calls = state
    for name in ("demo.zip", "demo.zip.sha256"):
        file = directory / name
        assets.append(
            {
                "name": name,
                "state": "uploaded",
                "size": file.stat().st_size,
                "digest": "sha256:" + mod.sha256(file),
            }
        )
    mod.main(manifest, directory)
    assert not any(call[0] == "UPLOAD" for call in calls)


@pytest.mark.parametrize("fault", ["multiple", "wrong_tag", "wrong_target", "wrong_asset"])
def test_conflicts_stop_without_writes(state, fault):
    mod, manifest, directory, release, candidates, assets, calls = state
    if fault == "multiple":
        candidates.append({**release, "id": 16})
    elif fault == "wrong_tag":
        release["tag_name"] = "v-wrong"
    elif fault == "wrong_target":
        release["target_commitish"] = "b" * 40
    else:
        assets.append({"name": "demo.zip", "state": "uploaded", "size": 1, "digest": "bad"})
    with pytest.raises(ValueError):
        mod.main(manifest, directory)
    assert not any(call[0] in ("WRITE", "UPLOAD") for call in calls)


@pytest.mark.parametrize("status", [403, 404])
def test_error_reports_endpoint(monkeypatch, status):
    monkeypatch.syspath_prepend(str(ROOT / "releases"))
    spec = importlib.util.spec_from_file_location(
        "publisher_error", ROOT / "releases/publish_windows.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, "", f"gh: failed (HTTP {status})"),
    )
    with pytest.raises(RuntimeError, match=rf"repos/example/project/releases/42.*HTTP {status}"):
        mod.gh("api", "repos/example/project/releases/42")


def test_create_failure_only_reads_before_stopping(state, monkeypatch):
    mod, manifest, directory, _, candidates, _, calls = state
    candidates.clear()

    def failed(*args):
        calls.append(("WRITE", *args))
        raise RuntimeError("POST HTTP 403")

    monkeypatch.setattr(mod, "gh", failed)
    with pytest.raises(RuntimeError, match="POST HTTP 403"):
        mod.main(manifest, directory)
    assert sum("POST" in call for call in calls) == 1
    assert sum(call[0] == "LIST" for call in calls) == 2
