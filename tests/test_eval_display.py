# SPDX-License-Identifier: Apache-2.0
"""窗口、计算书和输入规则的量值显示一致性。"""

from pathlib import Path

import pytest
from docx import Document
from openpyxl import load_workbook

from openpt.cli import calculate
from openpt.formatting import display_value
from openpt.io.validation import inspect_input
from openpt.report.docx import make_report
from openpt.windows_app import run_workbook, summarize

EXAMPLE = Path(__file__).resolve().parents[1] / "windows/examples/GB-T合成检测.xlsx"


@pytest.mark.parametrize("places", [0, 2, 4, None])
def test_window_and_docx_precision(tmp_path: Path, places: int | None) -> None:
    _, data, result = run_workbook(EXAMPLE, tmp_path / "run")
    data["config"]["display_value_decimals"] = places
    summary = summarize(data, result)
    report = tmp_path / "test.docx"
    make_report(report, data, result)
    doc = Document(report)
    text = "\n".join(
        [p.text for p in doc.paragraphs]
        + [c.text for t in doc.tables for r in t.rows for c in r.cells]
    )
    assigned = result["指定值与不确定度"]
    sig = int(data["config"].get("display_sig_digits") or 4)
    for key in ("value", "u", "sigma_final"):
        expected = display_value(assigned[key], sig, places)
        assert expected in summary and expected in text
    for p in data["participants"]:
        assert p["id"] in summary
        for name, score in result["参加者统计量"][p["id"]].items():
            assert name in summary
            if score["classification"]:
                assert score["classification"] in summary
            if score["value"] is not None:
                assert display_value(score["value"], places=2) in summary
    warnings = {
        w
        for scores in result["参加者统计量"].values()
        for s in scores.values()
        for w in s["warnings"]
    }
    for warning in warnings:
        assert summary.count(warning) == 1


@pytest.mark.parametrize("value", [-1, 1.5, "bad"])
def test_invalid_decimal_location(tmp_path: Path, value: object) -> None:
    book = load_workbook(EXAMPLE)
    book["方法配置"].append(["量值显示小数位（display_value_decimals）", value])
    row = book["方法配置"].max_row
    path = tmp_path / "invalid.xlsx"
    book.save(path)
    issues = inspect_input(path)
    assert any(i.code == "DISPLAY_VALUE_DECIMALS" and i.cell == f"B{row}" for i in issues)


def test_multi_and_warning(tmp_path: Path) -> None:
    _, data, result = run_workbook(EXAMPLE, tmp_path / "run")
    # 使用合成样例与较小的评定标准差，实际计算触发 z′ 建议。
    data["assigned_config"]["sigma_final"] = 0.01
    data["config"]["score_type"] = "all"
    result = calculate(data)
    summary = summarize(data, result)
    assert summary.count("u(X)≥0.3σ_pt；可考虑 z′") == 1
    for participant, scores in result["参加者统计量"].items():
        assert participant in summary
        assert set(scores) == {"D", "D%", "z", "zprime", "zeta", "En"}
    assert "未评价（" in summary
    multi = summarize(
        {"measurands": {"甲": data, "乙": data}}, {"被测量": {"甲": result, "乙": result}}
    )
    assert "被测量：甲" in multi and "被测量：乙" in multi
    assert multi.count("【参加者统计量】") == 2
