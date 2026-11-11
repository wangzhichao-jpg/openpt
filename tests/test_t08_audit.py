# SPDX-License-Identifier: Apache-2.0
"""审计包完整性与恶意路径测试。"""

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from hypothesis import given
from hypothesis import strategies as st

from openpt.audit import _safe_name, pack_directory, verify_zip
from openpt.cli import main
from openpt.errors import InputError


def _directory(path: Path) -> None:
    """创建人工构造的最小清单，不代表完整运行目录。"""
    path.mkdir()
    (path / "input").mkdir()
    (path / "input" / "data.csv").write_text("测试", encoding="utf-8")
    digest = hashlib.sha256((path / "input" / "data.csv").read_bytes()).hexdigest()
    (path / "manifest.json").write_text(
        json.dumps({"files": {"input/data.csv": digest}}), encoding="utf-8"
    )


def test_pack_verify_tamper_and_no_overwrite(tmp_path: Path) -> None:
    """正常文件、数据篡改及防覆盖。"""
    run = tmp_path / "run"
    _directory(run)
    output = tmp_path / "audit.zip"
    pack_directory(run, output)
    assert verify_zip(output) == []
    before = output.read_bytes()
    with pytest.raises(InputError, match="拒绝覆盖"):
        pack_directory(run, output)
    assert output.read_bytes() == before
    with ZipFile(output) as original:
        manifest = original.read("manifest.json")
    altered = tmp_path / "altered.zip"
    with ZipFile(altered, "w") as archive:
        archive.writestr("manifest.json", manifest)
        archive.writestr("input/data.csv", "modified")
    assert verify_zip(altered) == ["哈希不一致：input/data.csv"]
    assert main(["verify", str(altered)]) == 1
    (run / "input" / "data.csv").write_text("modified", encoding="utf-8")
    with pytest.raises(InputError, match="哈希不一致"):
        pack_directory(run, tmp_path / "another.zip")


@pytest.mark.parametrize("name", ["../outside", "/absolute", "x/../../escape", "x\\..\\escape"])
def test_reject_zip_slip(tmp_path: Path, name: str) -> None:
    """不解压不可信的穿越路径。"""
    archive = tmp_path / "evil.zip"
    with ZipFile(archive, "w") as output:
        output.writestr("manifest.json", '{"files": {}}')
        output.writestr(name, "bad")
    with pytest.raises(InputError, match="不安全"):
        verify_zip(archive)
    assert not (tmp_path.parent / "outside").exists()


@given(st.text(min_size=0, max_size=30))
def test_safe_name_always_rejects_parent_components(name: str) -> None:
    """任何含父路径组件的名称都不能通过。"""
    assert not _safe_name(f"{name}/../payload")
