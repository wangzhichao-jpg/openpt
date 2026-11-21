# SPDX-License-Identifier: Apache-2.0
"""计算书表格分隔、小量值和废弃显示参数的回归测试。"""

import copy
import json
import math
from itertools import pairwise
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn
from openpyxl import load_workbook

from openpt.cli import calculate, main
from openpt.formatting import display_value
from openpt.io.excel import read_workbook, template
from openpt.io.validation import inspect_input
from openpt.report.docx import make_report

ROOT = Path(__file__).resolve().parents[1]
WORKBOOKS = [
    *sorted((ROOT / "windows/examples").glob("*.xlsx")),
    ROOT / "windows/甲醛示例.xlsx",
    *sorted((ROOT / "examples/synthetic").glob("*.xlsx")),
]


def assert_separated(path: Path) -> None:
    body = list(Document(path).element.body)
    assert not any(a.tag == b.tag == qn("w:tbl") for a, b in pairwise(body))


@pytest.mark.parametrize("source", WORKBOOKS, ids=lambda p: p.stem)
def test_no_adjacent_tables_in_examples(source: Path, tmp_path: Path) -> None:
    data = read_workbook(source)
    report = tmp_path / "report.docx"
    make_report(report, data, calculate(data))
    assert_separated(report)


@pytest.mark.parametrize("standard", ["gl003", "gbt28043"])
def test_no_adjacent_tables_in_period_overrides(standard: str, tmp_path: Path) -> None:
    data = read_workbook(ROOT / "windows/examples/GB-T合成检测.xlsx")
    data["stability"]["运输期"] = copy.deepcopy(data["stability"]["稳定期"])
    data["config"]["criterion_standard"] = standard
    if standard == "gl003":
        data["assigned_config"]["hom_source"] = "manual"
        options = {
            "运输期": {"stability_method": "mean_difference", "baseline_source": "homogeneity"}
        }
    else:
        data["config"]["stability_u1"] = 0.5
        options = {"运输期": {"rule": "extended", "kind": "transport", "u2": 0.5}}
    data["config"]["stability_period_options"] = json.dumps(options, ensure_ascii=False)
    result = calculate(data)
    report = tmp_path / "period.docx"
    make_report(report, data, result)
    assert any("逐组评价准则" in p.text for p in Document(report).paragraphs)
    assert_separated(report)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0008131, "0.0008131"),
        (0.0036, "0.003600"),
        (2.18e-05, "0.00002180"),
        (5990.7, "5991"),
        (-0.0008131, "-0.0008131"),
        (0, "0.000"),
        (1e-7, "1.000e-07"),
        (1e6, "1.000e+06"),
    ],
)
def test_significant_values(value: float, expected: str) -> None:
    assert display_value(value) == expected


def test_small_homogeneity_end_to_end(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.xlsx"
    template(source)
    book = load_workbook(source)
    book["项目信息"]["B2"] = "合成小量值"
    book["项目信息"]["B3"] = "mg"
    book["方法配置"]["B3"] = 0.012
    book["方法配置"].append(["有效数字（display_sig_digits）", 3])
    book["方法配置"].append(["主判据（gl003_hom_criterion）", "ss_0.3sigma"])
    d = 0.0001
    a = math.sqrt(0.0008131**2 + d**2)
    for i, mean in enumerate((-a, 0.0, a)):
        for j, delta in enumerate((-d, d)):
            book["均匀性"].append([str(i), str(j), 0.4 + mean + delta, "mg"])
    book.save(source)
    report, output = tmp_path / "report.docx", tmp_path / "result.json"
    assert main(["run", str(source), "--docx", str(report), "--json", str(output)]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["均匀性"]["Ss"] == pytest.approx(0.0008131)
    doc = Document(report)
    table = next(
        t for t in doc.tables if t.cell(0, 0).text == "统计量" and t.cell(1, 0).text == "总平均值"
    )
    rows = {r.cells[0].text: r.cells[1].text for r in table.rows[1:]}
    assert rows["样品间标准差"] == "0.000813"
    assert rows["用途判据限值"] == "0.00360"
    assert any("Ss=0.000813 ≤ 0.3σ=0.00360" in p.text for p in doc.paragraphs)
    assert_separated(report)


@pytest.mark.parametrize("field", ["display_ss_decimals", "display_mean_decimals"])
def test_legacy_parameter_is_ignored_with_diagnostic(tmp_path: Path, field: str) -> None:
    book = load_workbook(ROOT / "windows/甲醛示例.xlsx")
    book["方法配置"].append([f"旧设置（{field}）", "废弃值"])
    source = tmp_path / "legacy.xlsx"
    book.save(source)
    assert inspect_input(source) == []
    data = read_workbook(source)
    result = calculate(data)
    assert any(
        field in item["说明"]
        and "已废弃" in item["说明"]
        and "display_value_decimals" in item["说明"]
        for item in result["诊断提示"]
    )
    report = tmp_path / "legacy.docx"
    make_report(report, data, result)
    assert any(field in p.text and "已废弃" in p.text for p in Document(report).paragraphs)


def test_optional_participant_values_are_dash(tmp_path: Path) -> None:
    data = read_workbook(ROOT / "windows/甲醛示例.xlsx")
    result = calculate(data)
    report = tmp_path / "participants.docx"
    make_report(report, data, result)
    doc = Document(report)
    table = next(
        t
        for t in doc.tables
        if [c.text for c in t.rows[0].cells][:3] == ["参加者", "测量值", "u(x)"]
    )
    for row, participant in zip(table.rows[1:], data["participants"], strict=True):
        for i, key in ((2, "u"), (3, "U"), (4, "k")):
            if participant.get(key) is None:
                assert row.cells[i].text == "—"
    assert "—：未提供" in [p.text for p in doc.paragraphs]
