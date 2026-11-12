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
        ("INSUFFICIENT_REPLICATES", "均匀性", "C2", 1.2),
        ("INSUFFICIENT_REPLICATES", "均匀性", "C4", "=1+2"),
        ("INSUFFICIENT_REPLICATES", "均匀性", "C5", None),
        ("MISSING_SHEET", "项目信息", "A1", None),
    }
    assert hashlib.sha256(path.read_bytes()).digest() == original


def test_csv_encoding_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """UTF-8 BOM 默认可读，GBK 必须明确声明。"""
    source = tmp_path / "input.csv"
    text = "单元编号,重复编号,值,单位\n甲,1,1.5,毫克\n甲,2,1.6,毫克\n乙,1,1.5,毫克\n乙,2,1.6,毫克\n"
    source.write_text(text, encoding="utf-8-sig")
    assert inspect_input(source) == []
    source.write_text(text, encoding="gbk")
    with pytest.raises(InputError, match="GBK"):
        inspect_input(source)
    assert main(["validate", str(source), "--encoding", "gbk"]) == 0
    assert capsys.readouterr().out.strip() == "[]"


def test_cross_sheet_units(tmp_path: Path) -> None:
    """不同工作表的单位不一致仍被定位。"""
    path = tmp_path / "input.xlsx"
    book = Workbook()
    first = book.active
    first.title = "均匀性"
    first.append(["单元编号", "重复编号", "值", "单位"])
    first.append(["A", 1, 1.0, "mg"])
    first.append(["A", 2, 1.1, "mg"])
    first.append(["B", 1, 1.0, "mg"])
    first.append(["B", 2, 1.1, "mg"])
    second = book.create_sheet("参加者结果")
    second.append(["参加者编号", "值", "单位"])
    second.append(["P1", 1.0, "g"])
    book.save(path)
    issues = inspect_input(path)
    assert ("UNIT_MISMATCH", "参加者结果", "C2", "g") in [
        (i.category, i.sheet, i.cell, i.original) for i in issues
    ]
    assert any(i.category == "MISSING_SHEET" and i.sheet == "项目信息" for i in issues)


def test_non_measurement_issues(tmp_path: Path) -> None:
    """声称值和其他表的公式问题也保留原始位置和值。"""
    path = tmp_path / "input.xlsx"
    book = Workbook()
    book.active.title = "均匀性"
    book.active.append(["单元编号", "重复编号", "值", "单位"])
    claims = book.create_sheet("报告声称值")
    claims.append(["统计量", "声称值", "显示小数位", "来源", "报告模型", "时间组"])
    claims.append(["F", "错误", 2, "报告", "", ""])
    config = book.create_sheet("方法配置")
    config.append(["字段", "值"])
    config.append(["alpha", "=1/20"])
    config.append(["sigma", "非数值"])
    book.save(path)
    issues = inspect_input(path)
    assert any(
        i.category == "NON_NUMERIC" and i.cell == "B2" and i.original == "错误" for i in issues
    )
    assert any(
        i.category == "FORMULA_NO_CACHE" and i.sheet == "方法配置" and i.original == "=1/20"
        for i in issues
    )
    assert any(
        i.category == "NON_NUMERIC" and i.cell == "B3" and i.original == "非数值" for i in issues
    )


@given(text=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=20))
def test_numeric_strings_rejected_as_xlsx_values(text: str) -> None:
    """XLSX 文字不视作数值，原始字符串保持不变。"""
    rows = [["单元编号", "重复编号", "值", "单位"], ["A", "1", text, "mg"]]
    issues = _check_rows("均匀性", rows, [], {})
    assert any(issue.category == "NON_NUMERIC" and issue.original == text for issue in issues)
