# SPDX-License-Identifier: Apache-2.0
"""判据与评价标准差的双向沿用与显式分离。"""

from pathlib import Path

import pytest
from docx import Document
from openpyxl import load_workbook

from openpt.cli import calculate
from openpt.io.excel import SHEETS, template
from openpt.report.docx import make_report


def _data(config: dict) -> dict:
    return {
        "config": {"assigned": 0.0, **config},
        "info": {},
        "homogeneity": [[1.0, 1.1], [1.2, 1.3]],
        "stability": {},
        "participants": [{"id": "P", "value": 1.0}],
        "claims": [],
    }


@pytest.mark.parametrize("config", [{"sigma": 2.0}, {"sigma_pt": 2.0}])
def test_sigma_single_value_reused(tmp_path: Path, config: dict) -> None:
    data = _data(config)
    result = calculate(data)
    assert result["均匀性"]["threshold"] == pytest.approx(0.6)
    assert result["参加者z"]["P"]["z"] == pytest.approx(0.5)
    report = tmp_path / "report.docx"
    make_report(report, data, result)
    assert "自动沿用该值" in "\n".join(p.text for p in Document(report).paragraphs)


def test_distinct_values_remain_distinct() -> None:
    result = calculate(_data({"sigma": 2.0, "sigma_pt": 4.0}))
    assert result["均匀性"]["threshold"] == pytest.approx(0.6)
    assert result["参加者z"]["P"]["z"] == pytest.approx(0.25)


def test_template_instructions_and_optional_marks(tmp_path: Path) -> None:
    path = tmp_path / "template.xlsx"
    template(path)
    book = load_workbook(path)
    text = "\n".join(str(cell.value) for row in book["填写说明"] for cell in row)
    assert "sigma 用于均匀性" in text and "至少填写一张" in text
    for name in set(SHEETS) - {"项目信息"}:
        assert "（选填）" in [cell.value for cell in book[name][1]]
