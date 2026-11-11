# SPDX-License-Identifier: Apache-2.0
"""固定模板的定位与错误处理。"""

from pathlib import Path

import pytest
from openpyxl import load_workbook

from openpt.cli import calculate, main
from openpt.errors import InputError
from openpt.io.excel import read_workbook, template


def _make(path: Path) -> None:
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "合成数据"
    book["项目信息"]["B3"] = "mg/kg"
    for uid, repeat, value in [("1", "1", 1), ("1", "2", 2), ("2", "1", 3), ("2", "2", 4)]:
        book["均匀性"].append([uid, repeat, value, "mg/kg"])
    book.save(path)


def test_required_fields_and_cli_exit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """空项目字段应退出2并给出中文提示。"""
    path = tmp_path / "blank.xlsx"
    template(path)
    assert (
        main(
            [
                "run",
                str(path),
                "--docx",
                str(tmp_path / "r.docx"),
                "--json",
                str(tmp_path / "r.json"),
            ]
        )
        == 2
    )
    assert "必填" in capsys.readouterr().err


@pytest.mark.parametrize("field,value", [("C2", "文字"), ("D2", "错误单位")])
def test_cell_type_and_unit(tmp_path: Path, field: str, value: str) -> None:
    """测量单元格和单位不正确时指向对应位置。"""
    path = tmp_path / "bad.xlsx"
    _make(path)
    book = load_workbook(path)
    book["均匀性"][field] = value
    book.save(path)
    with pytest.raises(ValueError, match=f"均匀性!{field}"):
        read_workbook(path)


def test_cli_rejects_overwriting_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """计算输出不能覆盖原始工作簿。"""
    path = tmp_path / "data.xlsx"
    _make(path)
    before = path.read_bytes()
    assert main(["run", str(path), "--docx", str(path)]) == 2
    assert "不得覆盖" in capsys.readouterr().err
    assert path.read_bytes() == before


def test_single_repeat_error_has_cell_location(tmp_path: Path) -> None:
    """GL003 4.2 无组内自由度时指出原始数据位置。"""
    path = tmp_path / "single.xlsx"
    _make(path)
    book = load_workbook(path)
    book["均匀性"].delete_rows(5)
    book["均匀性"].delete_rows(3)
    book.save(path)
    with pytest.raises(InputError, match="均匀性!C2"):
        read_workbook(path)


def test_invalid_zero_alpha_is_not_replaced(tmp_path: Path) -> None:
    """GL003 4.2 的显著性水平必须严格在零和一之间。"""
    path = tmp_path / "data.xlsx"
    _make(path)
    data = read_workbook(path)
    data["config"]["alpha"] = 0
    with pytest.raises(ValueError, match="alpha"):
        calculate(data)


def test_unequal_repetitions_and_empty_sheet(tmp_path: Path) -> None:
    """不平衡设计阻止计算；空数据表不得产生结果。"""
    path = tmp_path / "bad.xlsx"
    _make(path)
    book = load_workbook(path)
    book["均匀性"].delete_rows(5)
    book.save(path)
    with pytest.raises(ValueError, match="重复数不平衡"):
        read_workbook(path)
    book["均匀性"].delete_rows(2, 3)
    book.save(path)
    assert (
        main(
            [
                "run",
                str(path),
                "--docx",
                str(tmp_path / "r.docx"),
                "--json",
                str(tmp_path / "r.json"),
            ]
        )
        == 2
    )
