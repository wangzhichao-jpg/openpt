# SPDX-License-Identifier: Apache-2.0
"""发布前校验器必须拒绝摘要和布局不符的包。"""

import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_validation_025", ROOT / "releases/validate_windows_025.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _fixture(path: Path, fault: str = "") -> tuple[dict, Path]:
    app = "能力验证样品评价与定值工具"
    bundle = f"{app}_Windows.zip"
    cases = ["甲醛示例", "材料抗拉强度", "颗粒振实密度", "数字多用表", "GB-T合成检测"]
    projects = {
        "材料抗拉强度": "材料抗拉强度",
        "颗粒振实密度": "颗粒振实密度",
        "GB-T合成检测": "合成检测示例",
    }
    if fault == "missing_gbt":
        cases.remove("GB-T合成检测")
    if fault == "old_case":
        cases[1] = "金属材料抗拉强度"
    prefix = f"{app}/示例案例/"
    with zipfile.ZipFile(path / bundle, "w") as archive:
        archive.writestr(f"{app}/{app}.exe", b"XX" if fault == "exe" else b"MZ executable")
        for case in cases:
            if case in projects:
                book = Workbook()
                book.create_sheet("项目信息")["B2"] = (
                    "旧名称"
                    if (fault == "project" and case == "材料抗拉强度")
                    or (fault == "gbt_project" and case == "GB-T合成检测")
                    else projects[case]
                )
                stream = io.BytesIO()
                book.save(stream)
                content = stream.getvalue()
            else:
                content = case.encode()
            archive.writestr(prefix + case + ".xlsx", content)
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


@pytest.mark.parametrize(
    "fault",
    ["hash", "exe", "extra", "copies", "path", "project", "old_case", "missing_gbt", "gbt_project"],
)
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
        "release_publisher_025", ROOT / "releases/publish_windows_025.py"
    )
    assert spec and spec.loader
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/openpt")
    calls: list[tuple[str, ...]] = []

    release = {
        "id": 23,
        "draft": True,
        "name": publisher.TITLE,
        "tag_name": publisher.TAG,
        "target_commitish": "a" * 40,
        "prerelease": False,
    }

    def fake_api(path: str) -> dict:
        if "/git/ref/" in path:
            return {"object": {"sha": "a" * 40}}
        return release

    def fake_pages(path: str) -> list[dict]:
        calls.append((path,))
        if "/assets?" in path:
            return [
                {
                    "id": 100,
                    "name": manifest["bundle"],
                    "size": 1,
                    "digest": "sha256:wrong",
                    "state": "uploaded",
                }
            ]
        return [release]

    monkeypatch.setattr(publisher, "api", fake_api)
    monkeypatch.setattr(publisher, "list_pages", fake_pages)
    with pytest.raises(ValueError, match="拒绝覆盖"):
        publisher.main(manifest_path, directory)
    assert all("/releases" in call[0] for call in calls)


def _publisher(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.syspath_prepend(str(ROOT / "releases"))
    spec = importlib.util.spec_from_file_location(
        "release_publisher_025_tag", ROOT / "releases/publish_windows_025.py"
    )
    assert spec and spec.loader
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    return publisher


@pytest.mark.parametrize(
    ("ref", "annotated", "ok"),
    [
        ({"type": "commit", "sha": "a" * 40}, None, True),
        (
            {"type": "tag", "sha": "t" * 40},
            {"tag": "v0.2.5", "object": {"type": "commit", "sha": "a" * 40}},
            True,
        ),
        (
            {"type": "tag", "sha": "t" * 40},
            {"tag": "v0.2.5", "object": {"type": "commit", "sha": "b" * 40}},
            False,
        ),
        (
            {"type": "tag", "sha": "t" * 40},
            {"tag": "v0.2.3", "object": {"type": "commit", "sha": "a" * 40}},
            False,
        ),
        (
            {"type": "tag", "sha": "t" * 40},
            {"tag": "v0.2.5", "object": {"type": "tag", "sha": "a" * 40}},
            False,
        ),
        ({"type": "commit", "sha": "b" * 40}, None, False),
    ],
)
def test_tag_check_dereferences_annotated_tag_once(
    monkeypatch: pytest.MonkeyPatch, ref: dict, annotated: dict | None, ok: bool
) -> None:
    publisher = _publisher(monkeypatch)
    seen: list[str] = []

    def fake_api(path: str) -> dict:
        seen.append(path)
        if path.endswith("/git/ref/tags/v0.2.5"):
            return {"object": ref}
        if path.endswith("/git/tags/" + "t" * 40) and annotated is not None:
            return annotated
        raise AssertionError(path)

    monkeypatch.setattr(publisher, "api", fake_api)
    if ok:
        publisher.check_tag("repos/example/openpt", "a" * 40)
    else:
        with pytest.raises(ValueError):
            publisher.check_tag("repos/example/openpt", "a" * 40)
    assert len(seen) == (2 if ref["type"] == "tag" else 1)


def test_committed_manifest_matches_release_contract() -> None:
    manifest = json.loads((ROOT / "releases/windows-0.2.5.json").read_text(encoding="utf-8"))
    assert manifest["app"] == "能力验证样品评价与定值工具"
    assert set(manifest["cases"]) == {
        "甲醛示例",
        "材料抗拉强度",
        "颗粒振实密度",
        "数字多用表",
        "GB-T合成检测",
    }
    assert len(manifest["source_sha"]) == 40 and len(manifest["sha256"]) == 64
