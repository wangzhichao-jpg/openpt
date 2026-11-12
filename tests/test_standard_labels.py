# SPDX-License-Identifier: Apache-2.0
"""标准来源、冲突提示及差异表适用标准。"""

import csv
from pathlib import Path

import pytest
from docx import Document
from openpyxl import load_workbook

from openpt.cli import calculate
from openpt.core.gbt28043 import criterion_limit
from openpt.errors import InputError
from openpt.report.docx import make_report
from openpt.review.batch import write_xlsx
from openpt.review.compare import review, write_csv


def _data() -> dict:
    return {
        "info": {},
        "config": {"criterion_standard": "gbt28043", "sigma": 10.0, "sigma_pt": 20.0},
        "homogeneity": [[1.0, 1.1], [2.0, 2.1], [3.0, 3.1]],
        "stability": {},
        "participants": [],
        "claims": [{"name": "F", "value": 0.0, "digits": 2, "source": "合成"}],
    }


def test_conflict_message_explains_resolution() -> None:
    with pytest.raises(InputError, match=r"清空其中一个.*明确选择"):
        criterion_limit(1.0, 2.0)


@pytest.mark.parametrize(
    "fields, expected",
    [
        ({"sigma": 10.0, "sigma_pt": 20.0}, "sigma"),
        ({"sigma_pt": 10.0}, "sigma_pt"),
        ({"sigma": 10.0}, "sigma"),
    ],
)
def test_gbt_report_sigma_source(tmp_path: Path, fields: dict, expected: str) -> None:
    data = _data()
    data["config"] = {"criterion_standard": "gbt28043", **fields}
    path = tmp_path / "report.docx"
    make_report(path, data, calculate(data))
    assert any(f"σ_pt 取自配置字段 {expected}。" in p.text for p in Document(path).paragraphs)


def test_standard_column_all_outputs(tmp_path: Path) -> None:
    data = _data()
    result = calculate(data)
    rows = review(data, result)
    assert rows[0]["适用标准"] == "GL003"
    csv_path, xlsx_path, docx_path = (tmp_path / "a.csv", tmp_path / "a.xlsx", tmp_path / "a.docx")
    write_csv(csv_path, rows)
    write_xlsx(xlsx_path, rows)
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        assert next(csv.DictReader(stream))["适用标准"] == "GL003"
    values = list(load_workbook(xlsx_path).active.values)
    assert values[1][values[0].index("适用标准")] == "GL003"
    make_report(docx_path, data, result, rows)
    cells = [
        cell.text
        for table in Document(docx_path).tables
        for row in table.rows
        for cell in row.cells
    ]
    assert "适用标准" in cells and "GL003" in cells
