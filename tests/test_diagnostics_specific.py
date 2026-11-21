# SPDX-License-Identifier: Apache-2.0
"""基于合成工作簿验证未评价原因及修改建议。"""

from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook, load_workbook

from openpt.cli import _trend_transfer_diagnostics
from openpt.windows_app import run_workbook

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "windows/examples/GB-T合成检测.xlsx"
TRANSFER = ROOT / "examples/synthetic/transfer_synthetic.xlsx"
TREND = ROOT / "examples/synthetic/trend_synthetic.xlsx"


def _set(book: Workbook, sheet: str, field: str, value: Any) -> None:
    for row in book[sheet].iter_rows(min_row=2):
        label = str(row[0].value or "")
        if label == field or label.endswith(f"（{field}）"):
            row[1].value = value
            return
    book[sheet].append([field, value])


def _run(book: Workbook, root: Path) -> tuple[dict[str, Any], str]:
    path = root / "synthetic.xlsx"
    book.save(path)
    _, _, result = run_workbook(path, root / "runs")
    text = "\n".join(item["说明"] for item in result.get("诊断提示", []))
    return result, text


def _known(book: Workbook, statistic: str, value: float = 100) -> None:
    for field, value_ in (("method", "known"), ("value", value), ("uncertainty", 0.1)):
        _set(book, "指定值与不确定度", field, value_)
    _set(book, "方法配置", "score_type", statistic)


def test_trend_zero_slope_and_standard_error(tmp_path: Path) -> None:
    book = load_workbook(TREND)
    for row in book["趋势稳定性"].iter_rows(min_row=2):
        row[3].value = 5
    _, text = _run(book, tmp_path)
    assert "斜率和斜率标准误均为零" in text and "『趋势稳定性』" in text


def test_trend_uncertainty_source_missing(tmp_path: Path) -> None:
    book = load_workbook(TREND)
    for field, value in (
        ("method", "known"),
        ("value", 5),
        ("uncertainty", 0.1),
        ("source", "合成"),
        ("uncertainty_source", "合成"),
    ):
        _set(book, "指定值与不确定度", field, value)
    _, text = _run(book, tmp_path)
    assert "u_stab 来源" in text and "trend_short_series" in text and "stab_mapping" in text


def test_transfer_failed_criterion(tmp_path: Path) -> None:
    book = load_workbook(TRANSFER)
    book["传递标准配置"]["E2"] = '[{"kind":"fixed","value":0.01}]'
    result, text = _run(book, tmp_path)
    assert "判据 fixed 未通过（统计量 0.3，限值 0.01）" in text
    assert "0000000000" not in text
    assert result["传递标准稳定性"]["STD1|P1"]["criteria"][0]["value"] == 0.30000000000000004
    assert "传递标准稳定性未通过" in text and "判据JSON" in text


def test_transfer_diagnostic_defaults_to_six_significant_digits(tmp_path: Path) -> None:
    book = load_workbook(TRANSFER)
    book["传递标准配置"]["E2"] = '[{"kind":"fixed","value":0.01234567}]'
    result, text = _run(book, tmp_path)
    assert "统计量 0.3，限值 0.0123457" in text
    assert result["传递标准稳定性"]["STD1|P1"]["criteria"][0]["limit"] == 0.01234567


def test_transfer_diagnostic_uses_explicit_significant_digits(tmp_path: Path) -> None:
    book = load_workbook(TRANSFER)
    book["传递标准配置"]["E2"] = '[{"kind":"fixed","value":0.0123456}]'
    _set(book, "方法配置", "display_sig_digits", 3)
    result, text = _run(book, tmp_path)
    assert "统计量 0.3，限值 0.0123" in text
    assert result["传递标准稳定性"]["STD1|P1"]["criteria"][0]["limit"] == 0.0123456


def test_transfer_indeterminate_criterion(tmp_path: Path) -> None:
    book = load_workbook(TRANSFER)
    for row in book["传递标准复测"].iter_rows(min_row=2):
        row[5].value = 1
    book["传递标准配置"]["E2"] = '[{"kind":"one_sample","reference":1}]'
    _, text = _run(book, tmp_path)
    assert "判据 one_sample 未评价" in text and "标准误为零" in text
    assert "『传递标准复测』" in text and "判据JSON" in text


def test_transfer_mechanism_missing(tmp_path: Path) -> None:
    book = load_workbook(TRANSFER)
    book["传递标准配置"]["F2"] = None
    _, text = _run(book, tmp_path)
    assert "机制未登记" in text and "不确定度JSON" in text
    assert "传递标准稳定性衔接条件" in text and "mechanism、source" in text


def test_en_missing_u_and_k(tmp_path: Path) -> None:
    book = load_workbook(BASE)
    _known(book, "En")
    _set(book, "指定值与不确定度", "independent", True)
    _, text = _run(book, tmp_path)
    assert "双方扩展不确定度" in text and "U_assigned" in text and "包含因子k" in text


def test_en_unbound_transfer_point(tmp_path: Path) -> None:
    book = load_workbook(TRANSFER)
    _set(book, "方法配置", "transfer_en_map", "{}")
    _, text = _run(book, tmp_path)
    assert "未绑定唯一" in text and "transfer_en_map" in text


def test_en_missing_reference_uncertainty(tmp_path: Path) -> None:
    book = load_workbook(TRANSFER)
    book["传递标准配置"]["F2"] = '{"mechanism":"A","source":"合成"}'
    _set(book, "指定值与不确定度", "U_assigned", None)
    _, text = _run(book, tmp_path)
    assert "缺少参考值扩展不确定度" in text and "U_assigned" in text


def test_zeta_missing_u(tmp_path: Path) -> None:
    book = load_workbook(BASE)
    _known(book, "zeta")
    _set(book, "指定值与不确定度", "independent", True)
    _, text = _run(book, tmp_path)
    assert "参加者 u(x)" in text and "标准不确定度u(x)" in text


def test_zeta_independence_missing(tmp_path: Path) -> None:
    book = load_workbook(BASE)
    _known(book, "zeta")
    for row in book["参加者结果"].iter_rows(min_row=2):
        row[3].value = 0.1
    _set(book, "指定值与不确定度", "independent", None)
    _, text = _run(book, tmp_path)
    assert "不相关" in text and "independent" in text


def test_d_blocked_by_duplicate_component(tmp_path: Path) -> None:
    book = load_workbook(BASE)
    _known(book, "D")
    _set(book, "指定值与不确定度", "hom_mapping", "both")
    _, text = _run(book, tmp_path)
    assert "D 未评价" in text and "重复计入" in text and "hom_mapping" in text


def test_d_percent_zero_assigned(tmp_path: Path) -> None:
    book = load_workbook(BASE)
    _known(book, "D%", 0)
    _, text = _run(book, tmp_path)
    assert "指定值为零" in text and "『指定值与不确定度』value" in text


@pytest.mark.parametrize("statistic", ["z", "zprime"])
def test_z_sigma_missing(tmp_path: Path, statistic: str) -> None:
    book = load_workbook(BASE)
    _known(book, statistic)
    _set(book, "指定值与不确定度", "sigma_final", None)
    _set(book, "指定值与不确定度", "sigma_temporary", None)
    _, text = _run(book, tmp_path)
    assert "需要正的能力评定标准差" in text and "sigma_final" in text
    assert "sigma_temporary" in text and "sigma_procedure" in text
    assert "『方法配置』填写正的 sigma_pt" not in text


def test_legacy_z_sigma_missing_uses_method_config(tmp_path: Path) -> None:
    book = load_workbook(BASE)
    _set(book, "指定值与不确定度", "method", None)
    _set(book, "指定值与不确定度", "hom_source", "manual")
    _set(book, "方法配置", "criterion_standard", "gl003")
    _set(book, "方法配置", "assigned", 100)
    _set(book, "方法配置", "sigma", None)
    _set(book, "方法配置", "sigma_pt", None)
    result, text = _run(book, tmp_path)
    assert "z 未评价：需要正的能力评定标准差 σ_pt" in text
    assert "『方法配置』填写正的 sigma_pt 或 sigma" in text
    sigma_message = next(
        item["说明"] for item in result["诊断提示"] if "z 未评价：需要正的" in item["说明"]
    )
    assert "sigma_final" not in sigma_message and "sigma_procedure" not in sigma_message
    assert "参加者z" not in result


def test_fallback_when_no_reason_available() -> None:
    result = {
        "趋势稳定性": {"合成序列": {"stable": None}},
        "传递标准稳定性": {"A|B": {"conclusion": None}},
    }
    diagnostics = _trend_transfer_diagnostics({}, result)
    assert len(diagnostics) == 2
    assert all("结果未提供具体原因" in item["说明"] for item in diagnostics)
