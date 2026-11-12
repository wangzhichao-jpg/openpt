# SPDX-License-Identifier: Apache-2.0
"""趋势稳定性工作簿至计算和复核的合成流程。"""

from pathlib import Path

import pytest
from docx import Document
from openpyxl import load_workbook

from openpt.cli import calculate, main
from openpt.io.excel import read_workbook, template
from openpt.io.validation import inspect_input
from openpt.report.docx import make_report
from openpt.review.compare import review


def test_trend_end_to_end(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "合成"
    book["项目信息"]["B3"] = "mg"
    book["方法配置"]["B5"] = "回归趋势法"
    for x, y in ((0, 5.0), (1, 5.6), (2, 6.2), (4, 7.1), (5, 7.5)):
        book["趋势稳定性"].append(["短期", x, "天", y])
    for item in (
        ("b1", 0.1, 1, "合成", "", "短期"),
        ("b0", 5.08, 2, "合成", "", "短期"),
        ("趋势X̄", 2.4, 1, "合成", "", "短期"),
        ("趋势Ȳ", 6.28, 2, "合成", "", "短期"),
        ("趋势结论", 1, 0, "合成", "", "短期"),
    ):
        book["报告声称值"].append(item)
    book.save(path)
    assert inspect_input(path) == []
    data = read_workbook(path)
    result = calculate(data)
    assert result["趋势稳定性"]["短期"]["stable"] is False
    rows = review(data, result)
    assert any(row["差异类型"] == "INTERNAL_INCONSISTENT" for row in rows)
    assert any(row["统计量"] == "结论" and row["说明"] == "结论受影响" for row in rows)
    docx = tmp_path / "report.docx"
    make_report(docx, data, result, rows)
    text = "\n".join(p.text for p in Document(docx).paragraphs)
    assert "仅限微生物领域参考使用" in text and "未见原文" in text
    assert main(["run", str(path), "--runs-dir", str(tmp_path / "runs")]) == 0
    assert main(["review", str(path), "--runs-dir", str(tmp_path / "reviews")]) == 0
    assert main(["reproduce", str(next((tmp_path / "reviews").iterdir()))]) == 0


def test_trend_wide_time_mean_workbook(tmp_path: Path) -> None:
    path = tmp_path / "wide.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "合成"
    book["项目信息"]["B3"] = "mg"
    book["方法配置"]["B5"] = "回归趋势法"
    book["方法配置"]["B36"] = "time_mean"
    sheet = book["趋势稳定性"]
    sheet.delete_rows(1, sheet.max_row)
    sheet.append(["序列名", "时间单位", "时间=0", "时间=1", "时间=2"])
    sheet.append(["A", "月", 1.0, 1.1, 1.3])
    sheet.append(["B", "月", 1.2, 1.3, 1.5])
    book.save(path)
    assert inspect_input(path) == []
    data = read_workbook(path)
    assert data["trend_observations"][1]["source"] == "趋势稳定性!D2"
    assert calculate(data)["趋势稳定性"]["时间均值"]["n"] == 3


def test_trend_uncertainty_is_mapped_and_duplicate_reviewed(tmp_path: Path) -> None:
    path = tmp_path / "u.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "合成"
    book["项目信息"]["B3"] = "mg"
    config = book["方法配置"]
    config["B5"] = "回归趋势法"
    entries = {
        config.cell(i, 1).value.split("（")[-1].rstrip("）"): i
        for i in range(2, config.max_row + 1)
    }
    for field, value in {
        "trend_short_series": "短期",
        "trend_short_span": 14,
        "trend_long_series": "长期",
        "trend_long_span": 60,
    }.items():
        config.cell(entries[field], 2, value)
    for name, unit in (("短期", "天"), ("长期", "月")):
        for x, y in ((0, 1.0), (1, 1.2), (2, 1.1), (3, 1.3)):
            book["趋势稳定性"].append([name, x, unit, y])
    assigned = book["指定值与不确定度"]
    fields = {assigned.cell(i, 1).value: i for i in range(2, assigned.max_row + 1)}
    for key, value in {
        "method": "certified",
        "value": 1,
        "uncertainty": 0.1,
        "source": "证书",
        "uncertainty_source": "预算",
        "stab_mapping": "assigned",
    }.items():
        assigned.cell(fields[key], 2, value)
    book.save(path)
    data = read_workbook(path)
    result = calculate(data)
    assert result["趋势不确定度"]["u_stab"] > 0
    assert result["指定值与不确定度"]["u_stab"] == pytest.approx(result["趋势不确定度"]["u_stab"])
    data["config"]["trend_long_series"] = "短期"
    with pytest.raises(ValueError, match="不同序列"):
        calculate(data)
    data["config"]["trend_long_series"] = "长期"
    data["assigned_config"]["stab_in_base"] = True
    assert calculate(data)["指定值与不确定度"]["status"] == "DESIGN_REVIEW"
    data["assigned_config"]["u_stab"] = 1.0
    with pytest.raises(ValueError, match="不可同时"):
        calculate(data)


def test_optional_plot_absence_does_not_block_report(tmp_path: Path, monkeypatch) -> None:
    import builtins

    original = builtins.__import__

    def without_matplotlib(name, *args, **kwargs):
        if name.startswith("matplotlib"):
            raise ImportError("optional")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_matplotlib)
    data = {
        "info": {},
        "config": {"stability_method": "regression_trend", "trend_plot": True},
        "homogeneity": [],
        "stability": {},
        "participants": [],
        "claims": [],
        "trend_observations": [
            {"series": "A", "time_unit": "天", "x": x, "y": y}
            for x, y in ((0, 1.0), (1, 1.1), (2, 1.3))
        ],
    }
    target = tmp_path / "report.docx"
    make_report(target, data, calculate(data))
    assert "已跳过趋势图" in "\n".join(p.text for p in Document(target).paragraphs)


def test_trend_validation_too_few(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "合成"
    book["项目信息"]["B3"] = "mg"
    book["方法配置"]["B5"] = "回归趋势法"
    book["趋势稳定性"].append(["短期", 0, "天", 1])
    book["趋势稳定性"].append(["短期", 1, "天", 2])
    book.save(path)
    assert any(issue.category == "INPUT_ERROR" for issue in inspect_input(path))
    assert main(["run", str(path), "--runs-dir", str(tmp_path / "runs")]) == 2
    with pytest.raises(ValueError):
        calculate(read_workbook(path))
