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
            assert (path.parent / target).resolve().exists(), f"{name} -> {target}"


def test_download_versions_match_project_version() -> None:
    version = re.search(
        r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M
    )
    assert version
    for name in ("README.md", "README.en.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert f"releases/tag/v{version.group(1)}" in text
