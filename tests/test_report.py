# SPDX-License-Identifier: Apache-2.0
"""公开示例的计算书与机器输出核对。"""

import csv
import json
from pathlib import Path

from docx import Document
from openpyxl import load_workbook

from openpt.cli import main
from openpt.report.docx import _source_ranges


def test_report_matches_json(tmp_path: Path) -> None:
    """GL003 A.1 表1、2：DOCX 中的 F 按四位有效数字显示。"""
    source = Path(__file__).parents[1] / "examples" / "GL003_A1.xlsx"
    report = tmp_path / "result.docx"
    output = tmp_path / "result.json"
    assert main(["run", str(source), "--docx", str(report), "--json", str(output)]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    document = Document(report)
    cells = [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    for key in ("F", "F_critical", "p"):
        assert format(result["均匀性"][key], "#.4g") in cells
    assert "F 临界值" in cells
    text = "\n".join(p.text for p in document.paragraphs)
    assert "F=1.168 < F0.05(9,10)=3.020" in text
    assert "按 F 检验判定均匀" in text
    assert "未评价：未提供 σ" in text
    assert "均匀性!C2:C21" in text


def test_z_display_decimals_without_precision_loss(tmp_path: Path) -> None:
    """DOCX 默认两位、可配置三位；JSON 和 CSV 保留原精度。"""
    from openpt.demo import _synthetic

    source = tmp_path / "synthetic.xlsx"
    _synthetic(source)
    output, docx, diff = tmp_path / "r.json", tmp_path / "r.docx", tmp_path / "r.csv"
    args = [
        "review",
        str(source),
        "--docx",
        str(docx),
        "--json",
        str(output),
        "--differences",
        str(diff),
    ]
    assert main(args) == 0
    first = json.loads(output.read_text(encoding="utf-8"))
    table = next(t for t in Document(docx).tables if t.cell(0, 0).text == "参加者")
    assert table.cell(1, 2).text == "0.20"
    assert table.cell(2, 2).text == "0.00"
    with diff.open(encoding="utf-8-sig", newline="") as stream:
        original = list(csv.DictReader(stream))
    z_row = next(row for row in original if row["统计量"] == "z:P1")
    assert z_row["按报告模型复现值"] == "0.19607843137254902"
    book = load_workbook(source)
    for row in book["方法配置"].iter_rows(min_row=2):
        if row[0].value == "z 值显示小数位（display_z_decimals）":
            row[1].value = 3
    book.save(source)
    assert main(args) == 0
    table = next(t for t in Document(docx).tables if t.cell(0, 0).text == "参加者")
    assert table.cell(1, 2).text == "0.196"
    assert first == json.loads(output.read_text(encoding="utf-8"))
    with diff.open(encoding="utf-8-sig", newline="") as stream:
        assert original == list(csv.DictReader(stream))
    book = load_workbook(source)
    for row in book["方法配置"].iter_rows(min_row=2):
        if row[0].value == "z 值显示小数位（display_z_decimals）":
            row[1].value = 2.5
    book.save(source)
    assert main(args) == 2


def test_source_cell_rectangles() -> None:
    """合成的连续单元格位置应合并为工作表区域。"""
    assert _source_ranges(["表!C2", "表!D2", "表!C3", "表!D3"]) == ["表!C2:D3"]


def test_original_precision_controls_mean(tmp_path: Path) -> None:
    """合成数据设置两位小数，均值默认显示三位。"""
    from openpt.io.excel import template

    source = tmp_path / "input.xlsx"
    template(source)
    book = load_workbook(source)
    book["项目信息"]["B2"] = "合成数据"
    book["项目信息"]["B3"] = "mg/kg"
    for i in range(2):
        for j in range(2):
            book["均匀性"].append([str(i), str(j), float(i + j), "mg/kg"])
            book["均匀性"].cell(book["均匀性"].max_row, 3).number_format = "0.00"
    book.save(source)
    report, result = tmp_path / "r.docx", tmp_path / "r.json"
    assert main(["run", str(source), "--docx", str(report), "--json", str(result)]) == 0
    cells = [
        cell.text for table in Document(report).tables for row in table.rows for cell in row.cells
    ]
    assert "1.000" in cells
