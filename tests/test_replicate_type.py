# SPDX-License-Identifier: Apache-2.0
"""破坏性检测的单次测量和相邻试件。"""

from pathlib import Path

import pytest
from docx import Document
from openpyxl import load_workbook

from openpt.cli import calculate
from openpt.io.excel import read_workbook, template
from openpt.io.validation import inspect_input
from openpt.report.docx import make_report
from openpt.review.compare import review


def _workbook(path: Path, replicate_type: str) -> None:
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "合成项目"
    book["项目信息"]["B3"] = "mg"
    cfg = book["方法配置"]
    for row in cfg.iter_rows(min_row=2):
        if "（sigma）" in str(row[0].value):
            row[1].value = 1.0
        if "（replicate_type）" in str(row[0].value):
            row[1].value = replicate_type
    for unit, value in enumerate([1.0, 1.1, 1.2], 1):
        book["均匀性"].append([unit, 1, value, "mg"])
        if replicate_type != "single":
            book["均匀性"].append([unit, 2, value + 0.01, "mg"])
    book.save(path)


def test_single_workbook_and_report(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    _workbook(path, "single")
    assert inspect_input(path) == []
    data = read_workbook(path)
    result = calculate(data)
    h = result["均匀性"]
    assert h["Ss"] == pytest.approx(0.1)
    assert h["Ss_pass"] is True and h["F"] is None
    doc = tmp_path / "report.docx"
    make_report(doc, data, result)
    text = "\n".join(p.text for p in Document(doc).paragraphs)
    assert "B.1.2" in text and "不进行 F 检验" in text and "结论偏保守" in text
    data["config"].update({"criterion_standard": "gbt28043", "gbt_hom_rule": "extended"})
    result = calculate(data)
    assert result["GB/T均匀性"]["basic_pass"] is True
    assert result["GB/T均匀性"]["conclusion"] is None
    make_report(doc, data, result)
    text = "\n".join(p.text for p in Document(doc).paragraphs)
    assert "B.1.2" in text and "单测标准差" in text


def test_reject_single_with_multiple_repeats(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    _workbook(path, "single")
    book = load_workbook(path)
    book["均匀性"].append([1, 2, 1.05, "mg"])
    book.save(path)
    assert any(i.category == "INSUFFICIENT_REPLICATES" for i in inspect_input(path))
    with pytest.raises(ValueError, match="恰好"):
        read_workbook(path)


def test_adjacent_warning(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    _workbook(path, "adjacent_specimens")
    data = read_workbook(path)
    result = calculate(data)
    assert any("可能低估" in warning for warning in result["均匀性"]["warnings"])
    rows = review(data, result)
    assert any("DESTRUCTIVE_ADJACENT" in row["差异类型"] for row in rows)
