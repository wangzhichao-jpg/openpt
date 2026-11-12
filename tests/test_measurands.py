# SPDX-License-Identifier: Apache-2.0
"""多被测量隔离计算、来源和复核。"""

import csv
import json
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from openpyxl import load_workbook

from openpt.cli import calculate, main
from openpt.errors import InputError
from openpt.io.excel import read_workbook, template
from openpt.io.validation import inspect_input
from openpt.review.compare import review


def _make_multi(path: Path) -> None:
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "合成项目"
    book["项目信息"]["B3"] = "mg"
    hom = book["均匀性"]
    claims = book["报告声称值"]
    options = book["被测量配置"]
    for name, base, unit, sigma in (("甲", 1.0, "mg", 0.5), ("乙", 10.0, "mm", 2.0)):
        options.append([name, "单位", unit])
        options.append([name, "sigma", sigma])
        for uid in range(1, 4):
            for rep in (1, 2):
                hom.append([uid, rep, base + uid + rep / 10, unit, name])
        claims.append(["x̄", base + 2.15, 2, "合成报告", "", "", name])
    book.save(path)


def test_multi_calculation_review_and_reproduction(tmp_path: Path) -> None:
    path = tmp_path / "multi.xlsx"
    _make_multi(path)
    assert inspect_input(path) == []
    data = read_workbook(path)
    assert list(data["measurands"]) == ["甲", "乙"]
    assert data["measurands"]["甲"]["info"]["单位"] == "mg"
    assert data["measurands"]["乙"]["info"]["单位"] == "mm"
    result = calculate(data)
    assert result["被测量"]["甲"]["均匀性"]["threshold"] == pytest.approx(0.15)
    assert result["被测量"]["乙"]["均匀性"]["threshold"] == pytest.approx(0.6)
    assert all(row["状态"] == "MATCH" for row in review(data, result))
    assert data["measurands"]["甲"]["sources"][0] == "均匀性!C2"
    assert data["measurands"]["乙"]["sources"][0] == "均匀性!C8"
    assert (
        main(
            [
                "review",
                str(path),
                "--runs-dir",
                str(tmp_path / "runs"),
                "--json",
                str(tmp_path / "multi_结果.json"),
                "--docx",
                str(tmp_path / "multi_计算书.docx"),
                "--differences",
                str(tmp_path / "multi_差异.csv"),
            ]
        )
        == 0
    )
    output = json.loads((tmp_path / "multi_结果.json").read_text(encoding="utf-8"))
    assert output == result
    with (tmp_path / "multi_差异.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert {row["被测量"] for row in rows} == {"甲", "乙"}
    paragraphs = [p.text for p in Document(tmp_path / "multi_计算书.docx").paragraphs]
    assert "被测量：甲" in paragraphs and "被测量：乙" in paragraphs
    run = next((tmp_path / "runs").iterdir())
    assert main(["reproduce", str(run)]) == 0
    assert (
        main(
            [
                "decide",
                str(run),
                "--item",
                "被测量:甲/均匀性",
                "--decision",
                "需补充",
                "--by",
                "测试",
            ]
        )
        == 0
    )
    revision = Document(run / "report_rev_0001.docx")
    text = "\n".join(
        cell.text for table in revision.tables for row in table.rows for cell in row.cells
    )
    assert "需补充" in text
    per_measurement: dict[str, str] = {"甲": "", "乙": ""}
    current = ""
    for element in revision.element.body:
        if element.tag == qn("w:p"):
            label = Paragraph(element, revision).text
            if label.startswith("被测量："):
                current = label.removeprefix("被测量：")
        elif element.tag == qn("w:tbl") and current in per_measurement:
            per_measurement[current] += " ".join(
                node.text or "" for node in element.iter(qn("w:t"))
            )
    assert "需补充" in per_measurement["甲"]
    assert "需补充" not in per_measurement["乙"]
    assert main(["pack", str(run), "-o", str(tmp_path / "audit.zip")]) == 0
    assert main(["verify", str(tmp_path / "audit.zip")]) == 0


def test_mixed_or_missing_measurand_rejected(tmp_path: Path) -> None:
    path = tmp_path / "multi.xlsx"
    _make_multi(path)
    book = load_workbook(path)
    book["均匀性"]["E2"] = None
    book.save(path)
    with pytest.raises(InputError, match="被测量缺失"):
        inspect_input(path)
    with pytest.raises(InputError, match="被测量缺失"):
        read_workbook(path)


def test_configuration_and_data_errors_point_to_original_cells(tmp_path: Path) -> None:
    path = tmp_path / "multi.xlsx"
    _make_multi(path)
    book = load_workbook(path)
    book["被测量配置"]["C3"] = "非数值"
    book["均匀性"]["C8"] = None
    book.save(path)
    issues = inspect_input(path)
    assert any(
        i.category == "NON_NUMERIC" and i.sheet == "被测量配置" and i.cell == "C3" for i in issues
    )
    assert any(i.category == "MISSING" and i.sheet == "均匀性" and i.cell == "C8" for i in issues)


def test_invalid_per_measurand_configuration(tmp_path: Path) -> None:
    path = tmp_path / "multi.xlsx"
    _make_multi(path)
    book = load_workbook(path)
    book["被测量配置"].append(["甲", "sigma", 3])
    book.save(path)
    with pytest.raises(InputError, match="重复"):
        inspect_input(path)
