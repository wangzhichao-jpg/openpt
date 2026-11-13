# SPDX-License-Identifier: Apache-2.0
"""发布前校验器必须拒绝摘要和布局不符的包。"""

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_validation", ROOT / "releases/validate_windows.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _fixture(path: Path, fault: str = "") -> tuple[dict, Path]:
    app = "能力验证样品评价与定值工具"
    bundle = f"{app}_Windows.zip"
    cases = ["甲醛示例", "金属材料抗拉强度", "粉末振实密度", "数字多用表"]
    prefix = f"{app}/示例案例/"
    with zipfile.ZipFile(path / bundle, "w") as archive:
        archive.writestr(f"{app}/{app}.exe", b"XX" if fault == "exe" else b"MZ executable")
        for case in cases:
            archive.writestr(prefix + case + ".xlsx", case.encode())
        if fault == "extra":
            archive.writestr(prefix + "额外案例.xlsx", b"unexpected")
        original = "甲醛示例".encode()
        archive.writestr(f"{app}/甲醛示例.xlsx", original)
        archive.writestr(
            f"{app}/_internal/windows/甲醛示例.xlsx", b"wrong" if fault == "copies" else original
        )
        archive.writestr(prefix + "案例说明.txt", "说明")
        for name in ("LICENSE", "NOTICE", "THIRD_PARTY_LICENSES.md", "Python-LICENSE.txt"):
            archive.writestr(f"{app}/{name}", "license")
        if fault == "path":
            archive.writestr("../escape", "bad")
    raw = (path / bundle).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    (path / (bundle + ".sha256")).write_text(f"{digest}  {bundle}\n", encoding="utf-8")
    return {
        "app": app,
        "bundle": bundle,
        "bytes": len(raw),
        "sha256": "0" * 64 if fault == "hash" else digest,
        "cases": cases,
    }, path


def test_valid_release_artifact(tmp_path: Path) -> None:
    manifest, directory = _fixture(tmp_path)
    MODULE.validate(manifest, directory)
    json.dumps(manifest, ensure_ascii=False)


@pytest.mark.parametrize("fault", ["hash", "exe", "extra", "copies", "path"])
def test_rejects_invalid_release_artifact(tmp_path: Path, fault: str) -> None:
    manifest, directory = _fixture(tmp_path, fault)
    with pytest.raises(ValueError):
        MODULE.validate(manifest, directory)


def test_existing_mismatched_asset_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, directory = _fixture(tmp_path)
    manifest["source_sha"] = "a" * 40
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.syspath_prepend(str(ROOT / "releases"))
    spec = importlib.util.spec_from_file_location(
        "release_publisher", ROOT / "releases/publish_windows.py"
    )
    assert spec and spec.loader
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/openpt")
    calls: list[tuple[str, ...]] = []

    def fake_api(path: str, missing_ok: bool = False) -> dict:
        if "/git/ref/" in path:
            return {"object": {"sha": "a" * 40}}
        if "/commits/" in path:
            return {"sha": "a" * 40}
        return {"id": 1, "draft": True, "name": publisher.TITLE, "tag_name": publisher.TAG}

    def fake_gh(*args: str, missing_ok: bool = False) -> str:
        calls.append(args)
        assert args[0] == "api"
        return json.dumps(
            [{"name": manifest["bundle"], "size": 1, "digest": "sha256:wrong", "state": "uploaded"}]
        )

    monkeypatch.setattr(publisher, "api", fake_api)
    monkeypatch.setattr(publisher, "gh", fake_gh)
    with pytest.raises(ValueError, match="拒绝覆盖"):
        publisher.main(manifest_path, directory)
    assert all(call[0] == "api" for call in calls)
