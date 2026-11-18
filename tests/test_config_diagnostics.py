# SPDX-License-Identifier: Apache-2.0
"""配置预检及未评价提示的合成示例。"""

from pathlib import Path

import pytest
from docx import Document
from openpyxl import load_workbook

import openpt.cli as cli
from openpt.cli import _unevaluated_reason, calculate
from openpt.errors import InputError, locate
from openpt.io.excel import read_workbook
from openpt.io.validation import inspect_input
from openpt.windows_app import (
    error_dialog_summary,
    friendly_error,
    result_text_content,
    run_workbook,
    summarize,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "windows/examples/GB-T合成检测.xlsx"


def _set(book: object, sheet: str, field: str, value: object) -> None:
    for row in book[sheet].iter_rows(min_row=2):  # type: ignore[index]
        key = str(row[0].value)
        if key == field or key.endswith(f"（{field}）"):
            row[1].value = value
            return
    raise AssertionError(field)


def test_preflight_collects_multiple_configuration_errors(tmp_path: Path) -> None:
    book = load_workbook(EXAMPLE)
    for field, value in (("source", None), ("uncertainty_source", None), ("hom_mapping", "none")):
        _set(book, "指定值与不确定度", field, value)
    path = tmp_path / "invalid.xlsx"
    book.save(path)
    issues = inspect_input(path)
    messages = "\n".join(f"{i.sheet} {i.cell} {i.message}" for i in issues)
    assert "source" in messages and "uncertainty_source" in messages
    assert "hom_mapping" in messages and "hom_source=gbt_ss" in messages
    assert all(i.cell.startswith("B") for i in issues if i.sheet == "指定值与不确定度")


def test_static_errors_and_boolean_strings(tmp_path: Path) -> None:
    book = load_workbook(EXAMPLE)
    _set(book, "方法配置", "reference_uncertainty_negligible", "TRUE")
    _set(book, "指定值与不确定度", "hom_in_base", "FALSE")
    _set(book, "指定值与不确定度", "method", "known")
    _set(book, "指定值与不确定度", "source", None)
    _set(book, "指定值与不确定度", "sigma_final", -1)
    _set(book, "指定值与不确定度", "sigma_procedure", None)
    path = tmp_path / "multiple.xlsx"
    book.save(path)
    messages = "\n".join(issue.message for issue in inspect_input(path))
    for field in ("value", "uncertainty", "source", "sigma_final", "sigma_procedure"):
        assert field in messages
    assert "reference_uncertainty_negligible" not in messages
    assert "hom_in_base" not in messages


def test_missing_criterion_and_pending_are_explained(tmp_path: Path) -> None:
    book = load_workbook(EXAMPLE)
    _set(book, "方法配置", "sigma", None)
    path = tmp_path / "missing.xlsx"
    book.save(path)
    _, data, result = run_workbook(path, tmp_path / "runs")
    text = str(result["诊断提示"])
    assert "sigma_final" in text and "不作为均匀性" in text
    assert "pending" in text and "稳定期" in text
    assert result["诊断提示"][0]["层级"] == "根因"
    score = next(d for d in result["诊断提示"] if d["类型"] == "参加者统计量未评价")
    assert score["层级"] == "后果" and "分量映射" not in score["说明"]
    assert "稳定性处置" in score["说明"]
    assert summarize(data, result).startswith("【诊断提示】")


def test_gl003_diagnostic_and_report(tmp_path: Path) -> None:
    book = load_workbook(EXAMPLE)
    _set(book, "方法配置", "criterion_standard", "gl003")
    _set(book, "方法配置", "gl003_hom_criterion", "ss_0.3sigma")
    _set(book, "方法配置", "sigma", None)
    _set(book, "指定值与不确定度", "hom_source", "manual")
    path = tmp_path / "gl003.xlsx"
    book.save(path)
    directory, _, result = run_workbook(path, tmp_path / "runs")
    assert "均匀性未评价" in str(result["诊断提示"])
    paragraphs = [p.text for p in Document(directory / "report.docx").paragraphs]
    assert "诊断提示" in paragraphs
    assert any("判据 sigma 未填写" in p for p in paragraphs)


@pytest.mark.parametrize("statistic", ["zeta", "En"])
def test_missing_participant_uncertainty_grouped(tmp_path: Path, statistic: str) -> None:
    book = load_workbook(EXAMPLE)
    _set(book, "方法配置", "score_type", statistic)
    path = tmp_path / "score.xlsx"
    book.save(path)
    _, _, result = run_workbook(path, tmp_path / "runs")
    grouped = [d["说明"] for d in result["诊断提示"] if d["类型"] == "参加者统计量未评价"]
    assert len(grouped) == 1
    assert "P01" in grouped[0] and "P12" in grouped[0]
    assert ("u(x)" if statistic == "zeta" else "包含因子") in grouped[0]


def test_unallocated_transport_component_explained(tmp_path: Path) -> None:
    book = load_workbook(EXAMPLE)
    _set(book, "指定值与不确定度", "u_trans", 1)
    _set(book, "指定值与不确定度", "trans_mapping", "none")
    path = tmp_path / "transport.xlsx"
    book.save(path)
    _, _, result = run_workbook(path, tmp_path / "runs")
    assert "运输分量但未分配" in str(result["诊断提示"])


def test_withhold_explained(tmp_path: Path) -> None:
    book = load_workbook(EXAMPLE)
    _set(book, "指定值与不确定度", "stability_disposition", "withhold")
    path = tmp_path / "withhold.xlsx"
    book.save(path)
    _, _, result = run_workbook(path, tmp_path / "runs")
    assert "withhold" in str(result["诊断提示"])


def test_unevaluated_reason_details_and_fallback() -> None:
    assert "测量条件失效" in _unevaluated_reason(
        {"reason": "测量条件失效", "status": "NOT_EVALUATED"}, "兜底"
    )
    assert "采样不足" in _unevaluated_reason({"detail": {"warnings": ["采样不足"]}}, "兜底")
    assert "斜率和斜率标准误均为零" in _unevaluated_reason(
        {"status": "INDETERMINATE", "b1": 0, "s_b1": 0}, "兜底"
    )
    assert _unevaluated_reason({}, "兜底") == "兜底"


def test_result_area_and_dialog_summary() -> None:
    text = "输入校验问题：\n" + "\n".join(f"{i}. 错误" for i in range(8))
    assert result_text_content(text) == text
    assert "完整清单见结果区" in error_dialog_summary(text)
    assert "7. 错误" not in error_dialog_summary(text)
    assert "结果目录：" in result_text_content("【诊断提示】", Path("output"))


def test_calculation_errors_located(tmp_path: Path) -> None:
    book = load_workbook(EXAMPLE)
    _set(book, "方法配置", "sigma", None)
    _set(book, "指定值与不确定度", "stability_disposition", "reviewed")
    path = tmp_path / "reviewed.xlsx"
    book.save(path)
    with pytest.raises(InputError, match=r"第28行.*stability_disposition_reason"):
        run_workbook(path, tmp_path / "runs1")
    book = load_workbook(EXAMPLE)
    for field, value in (
        ("method", "known"),
        ("value", 100),
        ("uncertainty", 1),
        ("known_components", "1,2"),
    ):
        _set(book, "指定值与不确定度", field, value)
    path = tmp_path / "known.xlsx"
    book.save(path)
    with pytest.raises(InputError) as error:
        run_workbook(path, tmp_path / "runs2")
    assert "known_components" in friendly_error(error.value)
    path = tmp_path / "transfer.xlsx"
    book = load_workbook(
        Path(__file__).resolve().parents[1] / "examples/synthetic/transfer_synthetic.xlsx"
    )
    book["方法配置"].append(["transfer_en_map", "{bad"])
    book.save(path)
    with pytest.raises(InputError) as error:
        run_workbook(path, tmp_path / "runs3")
    assert "『方法配置』第45行" in friendly_error(error.value)
    assert "transfer_en_map" in friendly_error(error.value)


@pytest.mark.parametrize(
    ("sheet", "field", "value"),
    [
        ("指定值与不确定度", "method", "invalid"),
        ("指定值与不确定度", "source", None),
        ("指定值与不确定度", "uncertainty_source", None),
        ("指定值与不确定度", "sigma_final", -1),
        ("指定值与不确定度", "sigma_procedure", None),
        ("指定值与不确定度", "u_stab", -1),
        ("指定值与不确定度", "u_trans", -1),
        ("指定值与不确定度", "hom_mapping", "invalid"),
        ("指定值与不确定度", "stab_mapping", "invalid"),
        ("指定值与不确定度", "trans_mapping", "invalid"),
        ("指定值与不确定度", "hom_in_base", "invalid"),
        ("指定值与不确定度", "stability_disposition", "invalid"),
        ("方法配置", "alpha", 2),
        ("方法配置", "criterion_standard", "invalid"),
        ("方法配置", "trend_plot", "invalid"),
        ("方法配置", "sigma", -1),
    ],
)
def test_rule_preflight_and_calculation_agree(
    tmp_path: Path, sheet: str, field: str, value: object
) -> None:
    data = read_workbook(EXAMPLE)
    (data["config"] if sheet == "方法配置" else data["assigned_config"])[field] = value
    book = load_workbook(EXAMPLE)
    _set(book, sheet, field, value)
    path = tmp_path / "invalid.xlsx"
    book.save(path)
    assert any(field in issue.message for issue in inspect_input(path))
    with pytest.raises(InputError) as error:
        calculate(data)
    assert field in str(error.value)


def test_cross_standard_preflight_and_calculation(tmp_path: Path) -> None:
    data = read_workbook(EXAMPLE)
    data["config"]["criterion_standard"] = "gl003"
    book = load_workbook(EXAMPLE)
    _set(book, "方法配置", "criterion_standard", "gl003")
    path = tmp_path / "cross.xlsx"
    book.save(path)
    assert any("criterion_standard" in issue.message for issue in inspect_input(path))
    with pytest.raises(InputError, match="criterion_standard"):
        calculate(data)


def test_delta_e_missing_rule_in_preflight_and_calculation(tmp_path: Path) -> None:
    book = load_workbook(EXAMPLE)
    _set(book, "方法配置", "gbt_criterion_basis", "delta_e")
    _set(book, "方法配置", "delta_e", None)
    path = tmp_path / "delta.xlsx"
    book.save(path)
    assert any("delta_e" in issue.message for issue in inspect_input(path))
    data = read_workbook(path)
    with pytest.raises(InputError, match=r"『方法配置』第.*行.*delta_e"):
        calculate(data)


def test_csv_error_location_fallback(tmp_path: Path) -> None:
    path = tmp_path / "participants.csv"
    path.write_text("参加者编号,值,单位\nP01,1,mg\nP02,2,mg\n", encoding="utf-8")
    data = read_workbook(path, csv_sheet="参加者结果", unit="mg")
    data["config"].update(criterion_standard="gbt28043", gbt_criterion_basis="delta_e")
    with pytest.raises(InputError, match="『方法配置』字段 delta_e"):
        calculate(data)


@pytest.mark.parametrize(
    ("function", "sheet"),
    [
        ("homogeneity", "均匀性"),
        ("stability", "稳定性"),
        ("fit_series", "趋势稳定性"),
        ("algorithm_s", "算法S"),
    ],
)
def test_calculation_phase_error_names_sheet(
    monkeypatch: pytest.MonkeyPatch, function: str, sheet: str
) -> None:
    data = read_workbook(EXAMPLE)
    if function == "fit_series":
        data["config"]["stability_method"] = "regression_trend"
        data["trend_observations"] = [{"series": "x"}]
        data["stability"] = {}
    if function == "algorithm_s":
        data["algorithm_s_values"] = [1.0, 2.0]
        data["algorithm_s_df"] = 2

    def fail(*args: object, **kwargs: object) -> None:
        raise InputError("合成数据错误")

    monkeypatch.setattr(cli, function, fail)
    with pytest.raises(InputError, match=f"『{sheet}』：合成数据错误"):
        calculate(data)


def test_error_location_fallback() -> None:
    exc = InputError("无效", sheet="方法配置", field="sigma")
    assert str(locate(exc, {})) == "『方法配置』字段 sigma：无效"
    exc = InputError("无字段错误")
    assert locate(exc, {}) is exc
    exc = InputError("映射冲突", fields=["hom_mapping", "stab_mapping"])
    text = str(
        locate(
            exc,
            {
                "_cells": {
                    ("指定值与不确定度", "hom_mapping"): ("B13", "none"),
                    ("指定值与不确定度", "stab_mapping"): ("B14", "both"),
                }
            },
        )
    )
    assert "第13行 hom_mapping" in text and "第14行 stab_mapping" in text


def test_synthetic_gbt_example_scores(tmp_path: Path) -> None:
    _, _, result = run_workbook(EXAMPLE, tmp_path / "runs")
    assert result["指定值与不确定度"]["status"] == "OK"
    assert all(row["z"]["value"] is not None for row in result["参加者统计量"].values())
