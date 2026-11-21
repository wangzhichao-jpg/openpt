# SPDX-License-Identifier: Apache-2.0
"""参加者结果确定 σ_pt、分位数和 GB/T 8170 一次修约。"""

import copy
from pathlib import Path

import pytest
from docx import Document
from openpyxl import load_workbook

from openpt.cli import calculate, main
from openpt.core.robust import median_niqr
from openpt.core.sigma_pt import round_significant
from openpt.errors import InputError
from openpt.io.excel import read_workbook
from openpt.io.validation import inspect_input
from openpt.report.docx import make_report
from openpt.windows_app import run_workbook, summarize

ROOT = Path(__file__).resolve().parents[1]
LI = [1446, 1530, 1487, 1478, 1528, 1492, 1542, 1468]
HOU = [0.407, 0.402, 0.397, 0.411, 0.388, 0.328]


def data_for(values: list[float], method: str, quantile: str | None = None) -> dict:
    data = read_workbook(ROOT / "windows/examples/GB-T合成检测.xlsx")
    data["participants"] = [
        {"id": f"P{i}", "value": v, "source": f"合成!B{i}"} for i, v in enumerate(values, 1)
    ]
    data["config"].update(criterion_standard="gl003", quantile_method=quantile)
    data["assigned_config"].update(
        method="reference",
        value=100,
        uncertainty=1,
        hom_source="manual",
        hom_mapping="none",
        sigma_final=None,
        sigma_temporary=None,
        sigma_procedure="",
        sigma_pt_method=method,
    )
    return data


@pytest.mark.parametrize(
    ("value", "digits", "expected"),
    [
        (0.0115, 2, 0.012),
        (0.0125, 2, 0.012),
        (0.01149, 2, 0.011),
        (-0.0115, 2, -0.012),
        (-0.0125, 2, -0.012),
        (1.25001, 2, 1.3),
        (1.24501, 3, 1.25),
        (0, 2, 0),
    ],
)
def test_gbt8170_once(value: float, digits: int, expected: float) -> None:
    assert round_significant(value, digits) == expected


@pytest.mark.parametrize(("method", "expected"), [("linear", 39.2889), ("weibull", 43.7367)])
def test_li_quartiles_and_sigma(method: str, expected: float) -> None:
    data = data_for(LI, "niqr", method)
    data["assigned_config"]["sigma_pt_sig_digits"] = 3
    result = calculate(data)
    info = result["σ_pt确定"]
    assert info["raw"] == pytest.approx(expected, abs=0.002)
    assert info["value"] == (39.3 if method == "linear" else 43.7)
    assert result["指定值与不确定度"]["sigma_final"] == info["value"]
    assert result["指定值与不确定度"]["sigma_prime"] == info["value"]
    assert any("注2" in d["说明"] for d in result["诊断提示"])
    assert any("注3" in d["说明"] for d in result["诊断提示"])
    assert method in summarize(data, result)


def test_hou_auto_methods_and_no_chained_rounding() -> None:
    data = data_for(HOU, "niqr", "linear")
    data["assigned_config"]["sigma_pt_sig_digits"] = 2
    info = calculate(data)["σ_pt确定"]
    assert info["raw"] == pytest.approx(0.01149, abs=0.00001)
    assert info["value"] == 0.011
    for method in ("made", "algorithm_a"):
        data["assigned_config"].update(sigma_pt_method=method, sigma_pt_sig_digits=None)
        result = calculate(data)
        info = result["σ_pt确定"]
        if method == "algorithm_a":
            assert info["value"] == pytest.approx(0.01623, abs=1e-5)
            assert info["value"] == result["算法A"]["s"]
        else:
            assert info["value"] == pytest.approx(1.483 * 0.0095)
            assert any("注2" in d["说明"] for d in result["诊断提示"])


def test_criterion_explicit_uses_rounded_sigma(tmp_path: Path) -> None:
    data = data_for(LI, "niqr", "weibull")
    data["assigned_config"]["sigma_pt_sig_digits"] = 3
    data["config"].update(sigma=None, sigma_pt=None, criterion_sigma_source="sigma_pt")
    result = calculate(data)
    assert result["均匀性"]["threshold"] == pytest.approx(0.3 * 43.7)
    assert result["稳定性"]["threshold"] == pytest.approx(0.3 * 43.7)
    path = tmp_path / "report.docx"
    make_report(path, data, result)
    text = "\n".join(p.text for p in Document(path).paragraphs)
    for phrase in (
        "σ_pt 的确定",
        "weibull",
        "QUARTILE.EXC",
        "不得连续修约",
        "注2",
        "注3",
        "全部有效结果",
        "判据 σ 来源：显式",
    ):
        assert phrase in text
    assert "43.7" in summarize(data, result)


def test_weibull_requires_enough_data_for_excel_exc() -> None:
    with pytest.raises(InputError, match="至少需要三个"):
        median_niqr([1, 2], "weibull")
    data = data_for([1, 2], "manual", "weibull")
    with pytest.raises(InputError, match="至少需要三个"):
        calculate(data)


def test_no_automatic_criterion_backfill() -> None:
    data = data_for(LI, "niqr", "weibull")
    result = calculate(data)
    assert result["均匀性"]["threshold"] == pytest.approx(3.0)
    assert result["指定值与不确定度"]["sigma_final"] != 10


def test_algorithm_s_requires_standard_deviations() -> None:
    data = data_for(LI, "algorithm_s")
    data.update(algorithm_s_values=[1.0, 1.2, 1.4], algorithm_s_df=3)
    data["config"]["algorithm_s_input_type"] = "range"
    with pytest.raises(InputError, match="极差"):
        calculate(data)
    data["config"]["algorithm_s_input_type"] = "standard_deviation"
    result = calculate(data)
    assert result["σ_pt确定"]["value"] == result["算法S"]["w"]


def test_niqr_all_paths_follow_quantile_method() -> None:
    data = data_for(LI, "niqr", "weibull")
    data["assigned_config"].update(
        method="participant_consensus", consensus_method="median", value=None, uncertainty=None
    )
    result = calculate(data)
    assert result["中位数NIQR"]["niqr"] == pytest.approx(median_niqr(LI, "weibull").niqr)
    assert result["指定值与不确定度"]["base_u"] == pytest.approx(
        1.25 * result["中位数NIQR"]["niqr"] / len(LI) ** 0.5
    )
    for method in ("hazen", "median_unbiased"):
        data["config"]["quantile_method"] = method
        assert calculate(data)["中位数NIQR"]["niqr"] == median_niqr(LI, method).niqr


def test_preflight_locations(tmp_path: Path) -> None:
    book = load_workbook(ROOT / "windows/examples/GB-T合成检测.xlsx")
    book["指定值与不确定度"].append(["sigma_pt_method", "niqr"])
    path = tmp_path / "config.xlsx"
    book.save(path)
    issues = inspect_input(path)
    assert any(i.code == "SIGMA_PT_QUANTILE" for i in issues)
    assert any(i.code == "SIGMA_PT_CONFLICT" and i.cell for i in issues)


def test_workbook_snapshot_and_reproduce(tmp_path: Path) -> None:
    book = load_workbook(ROOT / "windows/examples/GB-T合成检测.xlsx")
    config = book["方法配置"]
    for row in config.iter_rows(min_row=2):
        if row[0].value and "（sigma）" in str(row[0].value):
            row[1].value = None
    for name, value in (("quantile_method", "weibull"), ("criterion_sigma_source", "sigma_pt")):
        config.append([name, value])
    assigned = book["指定值与不确定度"]
    updates = {
        "method": "reference",
        "value": 1490,
        "uncertainty": 1,
        "hom_source": "manual",
        "hom_mapping": "none",
        "sigma_final": None,
    }
    for row in assigned.iter_rows(min_row=2):
        if row[0].value in updates:
            row[1].value = updates[row[0].value]
    assigned.append(["sigma_pt_method", "niqr"])
    assigned.append(["sigma_pt_sig_digits", 3])
    book["项目信息"]["B3"] = "合成单位"
    for sheet_name, column in (("均匀性", 4), ("稳定性", 5)):
        for row in book[sheet_name].iter_rows(min_row=2):
            if row[0].value is not None:
                row[column - 1].value = "合成单位"
    sheet = book["参加者结果"]
    sheet.delete_rows(2, sheet.max_row)
    for i, value in enumerate(LI, 1):
        sheet.append([f"P{i}", value, book["项目信息"]["B3"].value])
    path = tmp_path / "synthetic.xlsx"
    book.save(path)
    assert not inspect_input(path)
    directory, data, result = run_workbook(path, tmp_path / "runs")
    assert result["σ_pt确定"]["value"] == 43.7
    assert "σ_pt = 43.7 " in summarize(data, result)
    assert main(["reproduce", str(directory)]) == 0


def test_manual_sigma_source_final() -> None:
    data = data_for(LI, "manual")
    data["assigned_config"].update(sigma_final=4.0, sigma_procedure="登记")
    data["config"].update(sigma=None, criterion_sigma_source="sigma_pt")
    result = calculate(data)
    assert result["均匀性"]["threshold"] == pytest.approx(1.2)
    missing = copy.deepcopy(data)
    missing["assigned_config"]["sigma_final"] = None
    with pytest.raises(InputError, match="最终"):
        calculate(missing)
