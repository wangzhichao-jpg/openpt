# SPDX-License-Identifier: Apache-2.0
"""只读导入检查、位置与编码。"""

import hashlib
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from openpyxl import Workbook

from openpt.cli import main
from openpt.errors import InputError
from openpt.io.validation import _check_rows, inspect_input


def test_xlsx_issues_and_mapping(tmp_path: Path) -> None:
    """五类问题带原始位置且不修改工作簿。"""
    path = tmp_path / "测量.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "均匀性"
    sheet.append(["样品", "次数", "读数", "单位"])
    sheet.append(["A", 1, 1.2, "mg"])
    sheet.append(["A", 1, "错误", "g"])
    sheet.append(["B", 1, "=1+2", "mg"])
    sheet.append(["C", 1, None, "mg"])
    book.save(path)
    original = hashlib.sha256(path.read_bytes()).digest()
    mapping = {"均匀性": {"单元编号": "样品", "重复编号": "次数", "值": "读数"}}
    issues = inspect_input(path, mapping)
    assert {(i.category, i.sheet, i.cell, i.original) for i in issues} == {
        ("NON_NUMERIC", "均匀性", "C3", "错误"),
        ("UNIT_MISMATCH", "均匀性", "D3", "g"),
        ("DUPLICATE", "均匀性", "B3", 1),
        ("FORMULA_NO_CACHE", "均匀性", "C4", "=1+2"),
        ("MISSING", "均匀性", "C5", None),
    }
    assert hashlib.sha256(path.read_bytes()).digest() == original


def test_csv_encoding_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """UTF-8 BOM 默认可读，GBK 必须明确声明。"""
    source = tmp_path / "input.csv"
    text = "单元编号,重复编号,值,单位\n甲,1,1.5,毫克\n"
    source.write_text(text, encoding="utf-8-sig")
    assert inspect_input(source) == []
    source.write_text(text, encoding="gbk")
    with pytest.raises(InputError, match="GBK"):
        inspect_input(source)
    assert main(["validate", str(source), "--encoding", "gbk"]) == 0
    assert capsys.readouterr().out.strip() == "[]"


@given(text=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=20))
def test_numeric_strings_rejected_as_xlsx_values(text: str) -> None:
    """XLSX 文字不视作数值，原始字符串保持不变。"""
    rows = [["单元编号", "重复编号", "值", "单位"], ["A", "1", text, "mg"]]
    issues = _check_rows("均匀性", rows, [], {})
    assert len(issues) == 1
    assert issues[0].category == "NON_NUMERIC" and issues[0].original == text
