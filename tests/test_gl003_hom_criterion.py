# SPDX-License-Identifier: Apache-2.0
"""GL003 均匀性主判据及兼容旧严格配置。"""

from pathlib import Path

import pytest
from docx import Document
from openpyxl import load_workbook

from openpt.cli import calculate
from openpt.errors import InputError
from openpt.io.excel import read_workbook, template
from openpt.report.docx import make_report
from openpt.review.compare import review


def _data() -> dict:
    return {
        "info": {},
        "config": {"sigma": 10.0},
        "homogeneity": [[1.0, 1.1], [2.0, 2.1], [3.0, 3.1]],
        "stability": {},
        "participants": [],
        "claims": [],
    }


def test_primary_modes_and_legacy_strict(tmp_path: Path) -> None:
    data = _data()
    assert calculate(data)["均匀性"]["conclusion"] is False
    data["config"]["gl003_hom_criterion"] = "ss_0.3sigma"
    result = calculate(data)
    h = result["均匀性"]
    assert h["F_pass"] is False and h["Ss_pass"] is True and h["conclusion"] is True
    target = tmp_path / "report.docx"
    make_report(target, data, result)
    paragraphs = [p.text for p in Document(target).paragraphs]
    assert "GL003 4.3 主判据" in paragraphs[1] and "通过" in paragraphs[1]
    assert "4.2" in paragraphs[1] and "参考" in paragraphs[1]
    assert any("以下 F 检验仅供参考" in p for p in paragraphs)
    data["config"]["gl003_hom_criterion"] = "both"
    assert calculate(data)["均匀性"]["conclusion"] is False
    data["config"]["gl003_hom_criterion"] = "ss_0.3sigma"
    data["config"]["strict_homogeneity"] = True
    assert calculate(data)["均匀性"]["selected_criterion"] == "both"
    assert calculate(data)["均匀性"]["conclusion"] is False
    data["config"]["strict_homogeneity"] = False
    data["config"]["sigma"] = None
    assert calculate(data)["均匀性"]["conclusion"] is None
    data["config"]["gl003_hom_criterion"] = "unknown"
    with pytest.raises(InputError):
        calculate(data)


def test_reported_criterion_switch_and_template(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "合成"
    book["项目信息"]["B3"] = "mg"
    book["方法配置"]["B3"] = 10.0
    book["方法配置"]["B34"] = "ss_0.3sigma"
    book["方法配置"]["B35"] = "f_test"
    for uid, row in enumerate(_data()["homogeneity"], 1):
        for repeat, value in enumerate(row, 1):
            book["均匀性"].append([uid, repeat, value, "mg"])
    book.save(path)
    data = read_workbook(path)
    result = calculate(data)
    assert result["均匀性"]["conclusion"] is True
    row = next(row for row in review(data, result) if row["统计量"] == "GL003均匀性主判据")
    assert row["差异类型"] == "MODEL_SWITCH" and row["状态"] == "NOTE"
    assert "ss_0.3sigma" in row["按推荐模型重算值"]
