# SPDX-License-Identifier: Apache-2.0
"""GitHub 默认英文、Gitee 默认中文，且两种语言可互相切换。"""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sync_readme", ROOT / "tools/sync_readme.py")
assert SPEC and SPEC.loader
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)


def test_github_readme_is_generated_from_english() -> None:
    expected = SYNC.render((ROOT / "README.en.md").read_text(encoding="utf-8"))
    assert (ROOT / ".github/README.md").read_text(encoding="utf-8") == expected


def test_language_switch_links() -> None:
    chinese = (ROOT / "README.md").read_text(encoding="utf-8")
    english = (ROOT / "README.en.md").read_text(encoding="utf-8")
    github = (ROOT / ".github/README.md").read_text(encoding="utf-8")
    assert "[English](README.en.md)" in chinese
    assert "[简体中文](README.md)" in english
    assert "[简体中文](../README.md)" in github


def test_relative_links_resolve() -> None:
    pattern = re.compile(r"\]\((?!https?://|mailto:|#)([^)\s]+)\)")
    for name in ("README.md", "README.en.md", ".github/README.md"):
        path = ROOT / name
        for target in pattern.findall(path.read_text(encoding="utf-8")):
            filename, _, fragment = target.partition("#")
            resolved = (path.parent / filename).resolve()
            assert resolved.exists(), f"{name} -> {target}"
            if fragment:
                assert f'id="{fragment}"' in resolved.read_text(encoding="utf-8")


def test_download_versions_match_latest_published_windows_manifest() -> None:
    """源码版本可领先已验收发布的 Windows 包。"""
    manifests = (ROOT / "releases").glob("windows-*.json")
    versions = [p.stem.removeprefix("windows-") for p in manifests]
    latest = max(versions, key=lambda value: tuple(int(part) for part in value.split(".")))
    project = re.search(
        r'^version = "([^\"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M
    )
    assert project
    for name in ("README.md", "README.en.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert f"releases/tag/v{latest}" in text
        if project.group(1) != latest:
            assert f"releases/tag/v{project.group(1)}" not in text
