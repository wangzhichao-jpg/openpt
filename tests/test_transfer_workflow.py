# SPDX-License-Identifier: Apache-2.0
"""传递标准合成工作簿、复核和 En 端到端测试。"""

import json
import math
from pathlib import Path

import pytest
from docx import Document
from openpyxl import load_workbook

from openpt.cli import calculate, main
from openpt.io.excel import read_workbook, template
from openpt.io.validation import inspect_input
from openpt.report.docx import make_report
from openpt.review.compare import review


def _workbook(path: Path, mechanism: str = "B") -> None:
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "合成"
    book["项目信息"]["B3"] = "V"
    book["方法配置"]["B42"] = "transfer_standard"
    sheet = book["传递标准复测"]
    for order, stage, value in (
        (1, "传递前", -1),
        (2, "传递中", 0.1),
        (3, "传递中", 0.4),
        (4, "传递后", 0.2),
    ):
        sheet.append(["STD1", "P1", order, "2025-01-01", stage, value, "V"])
    opts = {"mechanism": mechanism, "source": "合成报告"}
    if mechanism == "B":
        opts["multiplier"] = 2
    if mechanism == "C":
        opts.update(ignore_condition=True, condition_source="合成评定")
    book["传递标准配置"].append(
        [
            "STD1",
            "P1",
            "V",
            "transfer_only",
            json.dumps([{"kind": "fixed", "value": 1.0}]),
            json.dumps(opts, ensure_ascii=False),
            "合成报告第1页",
            None,
        ]
    )
    book["报告声称值"].append(["Δmax", 0.2, 2, "合成报告", "", "STD1|P1"])
    assigned = book["指定值与不确定度"]
    fields = {assigned.cell(i, 1).value: i for i in range(2, assigned.max_row + 1)}
    for key, value in {
        "method": "certified",
        "value": 1,
        "uncertainty": 0.1,
        "source": "合成证书",
        "uncertainty_source": "预算",
        "U_assigned": 2,
        "k_assigned": 2,
        "independent": True,
    }.items():
        assigned.cell(fields[key], 2, value)
    book["方法配置"]["B17"] = "En"
    book["参加者结果"].append(["P", 2.0, "V", 0.5, 1.0, 2.0])
    book.save(path)


def test_transfer_full_flow(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    _workbook(path)
    assert inspect_input(path) == []
    data = read_workbook(path)
    result = calculate(data)
    point = result["传递标准稳定性"]["STD1|P1"]
    assert point["delta_max"] == pytest.approx(0.3) and point["U_E"] == pytest.approx(0.6)
    assert result["传递标准汇总"]["standards"]["STD1"]["conclusion"] is True
    assert result["传递标准汇总"]["conclusion"] is True
    score = result["参加者统计量"]["P"]["En"]
    assert score["value"] == pytest.approx(1 / math.hypot(2, 1, 0.6))
    issue = next(row for row in review(data, result) if row["统计量"] == "Δmax")
    assert issue["差异类型"] == "VALUE_MISMATCH" and issue["说明"] == "结论不受影响"
    docx = tmp_path / "report.docx"
    make_report(docx, data, result, review(data, result))
    text = "\n".join(p.text for p in Document(docx).paragraphs)
    assert "单台传递标准，不适用样品间均匀性检验" in text and "JJF 1587 未见原文" in text
    assert main(["run", str(path), "--runs-dir", str(tmp_path / "runs")]) == 0
    assert main(["review", str(path), "--runs-dir", str(tmp_path / "reviews")]) == 0
    assert main(["reproduce", str(next((tmp_path / "reviews").iterdir()))]) == 0


def test_pretransfer_two_groups_are_independent(tmp_path: Path) -> None:
    path = tmp_path / "groups.xlsx"
    _workbook(path)
    book = load_workbook(path)
    sheet = book["传递标准复测"]
    sheet.delete_rows(2, sheet.max_row - 1)
    for group, values in (("甲", (1.0, 1.1, 1.2)), ("乙", (1.02, 1.12, 1.22))):
        for order, value in enumerate(values, 1):
            sheet.append(["STD1", "P1", order, "2025-01-01", "传递前", value, "V", group])
    config = book["传递标准配置"]
    config["D2"] = "all"
    config["E2"] = json.dumps([{"kind": "two_sample", "group1": "甲", "group2": "乙"}])
    book.save(path)
    assert inspect_input(path) == []
    point = calculate(read_workbook(path))["传递标准稳定性"]["STD1|P1"]
    detail = point["criteria"][0]["detail"]
    assert detail["n1"] == detail["n2"] == 3
    assert detail["mean1"] == pytest.approx(1.1)
    assert detail["mean2"] == pytest.approx(1.12)


def test_transfer_c_condition_is_checked(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    _workbook(path, "C")
    data = read_workbook(path)
    options = data["transfer_config"]["STD1|P1"]["uncertainty"]
    options.update(effect=0.4, measurement_uncertainty=0.9)
    result = calculate(data)
    assert result["传递标准稳定性"]["STD1|P1"]["uncertainty_status"] == "DESIGN_REVIEW"
    assert result["参加者统计量"]["P"]["En"]["status"] == "DESIGN_REVIEW"
    options["effect"] = 0.2
    assert calculate(data)["参加者统计量"]["P"]["En"]["status"] == "OK"


def test_transfer_a_and_duplicate_protection(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    _workbook(path, "A")
    data = read_workbook(path)
    result = calculate(data)
    assert result["参加者统计量"]["P"]["En"]["status"] == "OK"
    data["assigned_config"]["stab_in_base"] = True
    assert calculate(data)["参加者统计量"]["P"]["En"]["status"] == "DESIGN_REVIEW"
    data["assigned_config"]["stab_in_base"] = False
    data["transfer_config"]["STD1|P1"]["uncertainty"]["U_E"] = 0.3
    mixed = calculate(data)
    assert mixed["传递标准稳定性"]["STD1|P1"]["uncertainty_status"] == "DESIGN_REVIEW"
    assert mixed["参加者统计量"]["P"]["En"]["status"] == "DESIGN_REVIEW"
