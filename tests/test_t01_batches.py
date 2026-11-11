# SPDX-License-Identifier: Apache-2.0
"""候选批次登记、关联和比较。"""

from pathlib import Path

import pytest
from docx import Document
from openpyxl import load_workbook

from openpt.cli import main
from openpt.demo import _a1
from openpt.errors import InputError
from openpt.io.excel import read_workbook, template


def test_batch_report_three_formats(tmp_path: Path) -> None:
    """所有批次及统计量进入三格式计算书，状态不被自动改变。"""
    path = tmp_path / "input.xlsx"
    _a1(path)
    book = load_workbook(path)
    book["候选批次"].append(
        ["A", "物品", 1, "材质", "来源", "2025-01-01", "1,2,3", "失败", "不足", ""]
    )
    book["候选批次"].append(
        ["B", "物品", 1, "材质", "来源", "2025-01-02", "2,3,4", "候选", "", "A"]
    )
    book.save(path)
    runs = tmp_path / "runs"
    assert main(["run", str(path), "--runs-dir", str(runs)]) == 0
    root = next(runs.iterdir())
    doc = Document(root / "report.docx")
    table = next(t for t in doc.tables if t.cell(0, 0).text == "批次编号")
    assert [table.cell(1, 0).text, table.cell(2, 0).text] == ["A", "B"]
    assert table.cell(1, 6).text == "失败" and table.cell(2, 6).text == "候选"
    assert table.cell(1, 10).text == "2.0" and table.cell(2, 8).text == "A"
    html = (root / "report.html").read_text(encoding="utf-8")
    assert "候选批次追溯" in html and "失败" in html and "候选" in html
    xlsx = load_workbook(root / "report.xlsx", data_only=False)
    assert "候选批次追溯" in xlsx.sheetnames
    assert any(cell.value == "失败" for row in xlsx["候选批次追溯"] for cell in row)


def test_batch_trace_and_comparison(tmp_path: Path) -> None:
    """登记候选及失败批次，保留人工选用状态和预实验统计量。"""
    path = tmp_path / "input.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "虚构项目"
    book["项目信息"]["B3"] = "mg"
    sheet = book["候选批次"]
    sheet.append(["A", "物品", 1, "材质", "来源", "2025-01-01", "1,2,3", "失败", "不足", ""])
    sheet.append(["B", "物品", 1, "材质", "来源", "2025-01-02", "2,3,4", "候选", "", "A"])
    book.save(path)
    batches = read_workbook(path)["batches"]
    assert [b["状态"] for b in batches] == ["失败", "候选"]
    assert batches[0]["预实验均值"] == 2 and batches[0]["预实验标准差"] == 1
    assert batches[1]["关联批次"] == "A"
    sheet["I2"] = None
    book.save(path)
    with pytest.raises(InputError, match="须填写理由"):
        read_workbook(path)
    sheet["I2"] = "不足"
    sheet["J3"] = "不存在"
    book.save(path)
    with pytest.raises(InputError, match="关联批次"):
        read_workbook(path)
