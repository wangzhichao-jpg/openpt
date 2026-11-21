# SPDX-License-Identifier: Apache-2.0
"""参加者描述统计、按被测量隔离和来源文字提示。"""

import copy
import math
import subprocess
import sys
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn
from openpyxl import load_workbook

from openpt.cli import calculate, main
from openpt.config.field_labels import field_key
from openpt.config.source_diagnostics import source_diagnostics
from openpt.io.excel import read_workbook, template
from openpt.io.validation import inspect_input
from openpt.report.docx import make_report
from openpt.windows_app import run_workbook, summarize

ROOT = Path(__file__).resolve().parents[1]
HOU = [0.407, 0.402, 0.397, 0.411, 0.388, 0.328]
EXAMPLE = ROOT / "windows/甲醛示例.xlsx"
INPUTS = [
    *sorted((ROOT / "windows/examples").glob("*.xlsx")),
    EXAMPLE,
    *[
        p
        for p in sorted((ROOT / "examples").rglob("*.xlsx"))
        if not (p.parent.name == "trace_run" and p.name in {"report.xlsx", "report_rev_0001.xlsx"})
    ],
]


def data_for(values: list[float]) -> dict:
    data = read_workbook(EXAMPLE)
    data["participants"] = [
        {"id": f"T{i}", "value": value, "source": f"参加者结果!B{i + 1}"}
        for i, value in enumerate(values, 1)
    ]
    return data


def report_rows(doc: Document) -> dict[str, str]:
    table = next(
        t for t in doc.tables if t.cell(0, 0).text == "统计量" and t.cell(1, 0).text == "结果数 p"
    )
    return {row.cells[0].text: row.cells[1].text for row in table.rows[1:]}


def assert_separated(doc: Document) -> None:
    from itertools import pairwise

    assert not any(a.tag == b.tag == qn("w:tbl") for a, b in pairwise(doc.element.body))


def test_hou_statistics_end_to_end(tmp_path: Path) -> None:
    data = data_for(HOU)
    result = calculate(data)
    stat = result["参加者结果统计量"]
    assert stat["n"] == 6 and stat["median"] == pytest.approx(0.3995)
    assert stat["min"] == 0.328 and stat["max"] == 0.411
    assert stat["range"] == pytest.approx(0.083)
    assert stat["niqr"] == pytest.approx(0.01149015)
    assert stat["robust_cv_percent"] == pytest.approx(0.01149015 / 0.3995 * 100)
    assert stat["mean"] == pytest.approx(sum(HOU) / len(HOU))
    path = tmp_path / "report.docx"
    make_report(path, data, result)
    doc = Document(path)
    rows = report_rows(doc)
    assert rows["结果数 p"] == "6" and rows["中位值"] == "0.3995"
    assert rows["NIQR"] == "0.01149" and rows["稳健 CV（%）"] == "2.876"
    assert float(rows["最小值"]) == 0.328 and float(rows["最大值"]) == 0.411
    assert float(rows["极差"]) == 0.083
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "表 B1 及表注 2" in text and "仅供参考，未剔除离群值" in text
    assert "参加者结果：p=6，中位值 0.3995，NIQR 0.01149，稳健 CV 2.876%" in summarize(data, result)
    assert_separated(doc)


def test_zero_median_and_quantile_choice(tmp_path: Path) -> None:
    data = data_for([-3, -1, 1, 3])
    data["config"]["quantile_method"] = "weibull"
    result = calculate(data)
    stat = result["参加者结果统计量"]
    assert stat["median"] == 0 and stat["robust_cv_percent"] is None
    assert stat["niqr"] == pytest.approx(0.7413 * 5)
    path = tmp_path / "zero.docx"
    make_report(path, data, result)
    doc = Document(path)
    assert report_rows(doc)["稳健 CV（%）"] == "—"
    assert any("中位值为零" in p.text for p in doc.paragraphs)
    assert any("weibull" in p.text and "QUARTILE.EXC" in p.text for p in doc.paragraphs)
    assert "稳健 CV —" in summarize(data, result)


def test_one_result_descriptive_statistics(tmp_path: Path) -> None:
    data = data_for([1])
    data["assigned_config"].update(
        method="reference",
        value=1,
        uncertainty=0.1,
        source="独立来源",
        uncertainty_source="独立预算",
    )
    result = calculate(data)
    assert result["参加者结果统计量"]["n"] == 1
    assert result["参加者结果统计量"]["sd"] is None
    path = tmp_path / "one.docx"
    make_report(path, data, result)
    assert any("至少需要两个结果" in p.text for p in Document(path).paragraphs)


def test_multiple_measurand_source_original_location(tmp_path: Path) -> None:
    path = tmp_path / "multi-source.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "多量合成"
    book["项目信息"]["B3"] = "mg"
    book["被测量配置"].append(["甲", "sigma_source", "合成示例：项目预定目标标准差"])
    sheet = book["参加者结果"]
    for name in ("甲", "乙"):
        for i in range(3):
            sheet.append([f"P{i}", i + 1, "mg", None, None, None, name])
    book.save(path)
    result = calculate(read_workbook(path))
    warnings = result["被测量"]["甲"]["诊断提示"]
    assert any("『被测量配置』C2（sigma_source）" in w["说明"] for w in warnings)


def test_multiple_measurands_isolated_workbook(tmp_path: Path) -> None:
    path = tmp_path / "multi.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "多量合成"
    book["项目信息"]["B3"] = "mg"
    sheet = book["参加者结果"]
    assert sheet["G1"].value == "被测量"
    for name, values in (("甲", HOU), ("乙", [10, 11, 12, 13])):
        for i, value in enumerate(values):
            sheet.append([f"P{i}", value, "mg", None, None, None, name])
    book.save(path)
    assert inspect_input(path) == []
    data = read_workbook(path)
    result = calculate(data)
    assert result["被测量"]["甲"]["参加者结果统计量"]["n"] == 6
    assert result["被测量"]["乙"]["参加者结果统计量"]["n"] == 4
    assert result["被测量"]["甲"]["参加者结果统计量"]["median"] == pytest.approx(0.3995)
    assert result["被测量"]["乙"]["参加者结果统计量"]["median"] == 11.5
    assert len(data["measurands"]["甲"]["participants"]) == 6
    assert len(data["measurands"]["乙"]["participants"]) == 4
    report = tmp_path / "multi.docx"
    make_report(report, data, result)
    doc = Document(report)
    tables = [
        t for t in doc.tables if t.cell(0, 0).text == "统计量" and t.cell(1, 0).text == "结果数 p"
    ]
    assert [t.cell(1, 1).text for t in tables] == ["6", "4"]
    assert_separated(doc)
    assert main(["run", str(path), "--runs-dir", str(tmp_path / "runs")]) == 0
    run = next((tmp_path / "runs").iterdir())
    assert main(["reproduce", str(run)]) == 0
    book = load_workbook(path)
    book["参加者结果"]["G2"] = None
    book.save(path)
    with pytest.raises(ValueError, match="被测量缺失"):
        read_workbook(path)


@pytest.mark.parametrize("change", ["project", "method", "participants"])
def test_reused_example_text_detects_changed_context(change: str) -> None:
    data = read_workbook(EXAMPLE)
    assert not source_diagnostics(data)
    data = copy.deepcopy(data)
    if change == "project":
        data["info"]["项目名称"] = "其他项目"
    elif change == "method":
        data["assigned_config"]["method"] = "certified"
    else:
        data["participants"][0]["value"] += 0.01
    warnings = source_diagnostics(data)
    source = [w["说明"] for w in warnings if w["类型"] == "示例来源沿用"]
    assert len(source) == 4
    assert any("（source）" in w and "B5" in w for w in source)
    assert any("（sigma_procedure）" in w and "B10" in w for w in source)
    assert any("（sigma_source）" in w for w in source)
    assert all("请按本项目实际情况改写" in w for w in source)


@pytest.mark.parametrize("method", ["known", "certified", "reference", "expert_consensus"])
def test_incompatible_consensus_wording(method: str) -> None:
    data = read_workbook(EXAMPLE)
    data["assigned_config"].update(
        method=method, source="由参加者提供", uncertainty_source="算法 A 公议"
    )
    warnings = [w for w in source_diagnostics(data) if w["类型"] == "来源方法矛盾"]
    assert len(warnings) == 2
    assert all("可能与定值方法不一致" in w["说明"] for w in warnings)
    assert any("B5" in w["说明"] for w in warnings)


def test_changed_example_sources_are_nonblocking_end_to_end(tmp_path: Path) -> None:
    book = load_workbook(EXAMPLE)
    sheet = book["指定值与不确定度"]
    values = {"method": "certified", "value": 100, "uncertainty": 0.1}
    for row in sheet.iter_rows(min_row=2):
        if field_key(row[0].value) in values:
            row[1].value = values[field_key(row[0].value)]
    path = tmp_path / "copy.xlsx"
    book.save(path)
    assert inspect_input(path) == []
    directory, _, result = run_workbook(path, tmp_path / "runs")
    warnings = result["诊断提示"]
    assert result["指定值与不确定度"]["value"] == 100
    assert any(w["类型"] == "示例来源沿用" and "（source）" in w["说明"] for w in warnings)
    assert any(
        w["类型"] == "示例来源沿用" and "（uncertainty_source）" in w["说明"] for w in warnings
    )
    assert sum(w["类型"] == "来源方法矛盾" for w in warnings) == 2
    text = "\n".join(p.text for p in Document(directory / "report.docx").paragraphs)
    assert "来源说明可能与定值方法不一致" in text
    assert "来源说明与随包示例原文相同" in text


def test_incompatible_certified_wording_and_nonblocking() -> None:
    data = read_workbook(EXAMPLE)
    data["assigned_config"].update(source="CRM 标准物质", uncertainty_source="参考实验室证书")
    result = calculate(data)
    warnings = [w for w in result["诊断提示"] if w["类型"] == "来源方法矛盾"]
    assert len(warnings) == 2 and result["算法A"]["converged"]


def test_example_index_and_no_false_positives() -> None:
    assert len(INPUTS) == 19
    subprocess.run(
        [sys.executable, str(ROOT / "tools/generate_example_sources.py"), "--check"], check=True
    )
    for path in INPUTS:
        data = read_workbook(path)
        result = calculate(data)
        parts = result.get("被测量", {}).values() if result.get("被测量") else [result]
        for part in parts:
            assert not [
                item
                for item in part.get("诊断提示", [])
                if item["类型"] in ("示例来源沿用", "来源方法矛盾")
            ], path


def test_reused_example_text_across_fields() -> None:
    data = read_workbook(EXAMPLE)
    data["info"]["项目名称"] = "其他项目"
    data["assigned_config"]["source"] = data["assigned_config"]["uncertainty_source"]
    assert any(
        w["类型"] == "示例来源沿用" and "（source）" in w["说明"] for w in source_diagnostics(data)
    )


def test_exact_text_comparison_and_order_independence() -> None:
    data = read_workbook(EXAMPLE)
    data["participants"].reverse()
    assert not source_diagnostics(data)
    data["info"]["项目名称"] = "其他项目"
    data["assigned_config"]["source"] += " "
    warnings = source_diagnostics(data)
    assert not any(w["类型"] == "示例来源沿用" and "（source）" in w["说明"] for w in warnings)
    assert not math.isnan(calculate(data)["参加者结果统计量"]["mean"])
