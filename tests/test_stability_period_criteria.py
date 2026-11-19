# SPDX-License-Identifier: Apache-2.0
"""逐时间组配置的计算与输入校验。"""

import copy
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from openpt.cli import calculate
from openpt.errors import InputError, format_error
from openpt.io.excel import read_workbook
from openpt.io.validation import inspect_input

EXAMPLE = Path(__file__).resolve().parents[1] / "windows/examples/GB-T合成检测.xlsx"


def data_for(standard: str, options: dict) -> dict:
    data = read_workbook(EXAMPLE)
    data["stability"]["运输期"] = copy.deepcopy(data["stability"]["稳定期"])
    data["config"]["criterion_standard"] = standard
    data["config"]["stability_method"] = "two_sample"
    data["config"]["stability_period_options"] = json.dumps(options, ensure_ascii=False)
    if standard == "gl003":
        data["assigned_config"]["hom_source"] = "manual"
    return data


def test_gbt_group_rules_and_basis() -> None:
    data = data_for(
        "gbt28043",
        {
            "稳定期": {"rule": "basic"},
            "运输期": {"rule": "extended", "kind": "transport", "u2": 0.5},
        },
    )
    data["config"]["stability_u1"] = 0.5
    data["stability"]["运输期"] = [
        [value + 3.4 for value in row] for row in data["stability"]["基线"]
    ]
    result = calculate(data)["GB/T稳定性"]
    assert result["稳定期"]["selected_rule"] == "basic"
    assert result["运输期"]["selected_rule"] == "extended"
    assert result["运输期"]["basic_pass"] is False
    assert result["运输期"]["extended_pass"] is True
    assert result["运输期"]["extended_limit"] > result["运输期"]["basic_limit"]
    for name in result:
        item = result[name]
        assert item["conclusion"] == item[item["selected_rule"] + "_pass"]
        assert item["criterion_settings"]["rule"]["source"] == "逐组设置"
    data["config"]["stability_period_options"] = json.dumps(
        {"运输期": {"basis": "delta_e", "delta_e": 50}}
    )
    result = calculate(data)["GB/T稳定性"]
    assert result["运输期"]["criterion_basis"] == "delta_e"
    assert result["运输期"]["basic_limit"] == 5
    assert result["稳定期"]["criterion_basis"] == "sigma_pt"


def test_gl003_mixed_baselines() -> None:
    options = {
        "稳定期": {"stability_method": "two_sample", "baseline_source": "baseline_group"},
        "运输期": {"stability_method": "mean_difference", "baseline_source": "homogeneity"},
    }
    data = data_for("gl003", options)
    result = calculate(data)
    assert result["稳定性"]["method"] == "two_sample"
    assert result["其他稳定性"]["运输期"]["method"] == "mean_difference"
    assert result["其他稳定性"]["运输期"]["criterion_settings"]["baseline_source"] == {
        "value": "homogeneity",
        "source": "逐组设置",
    }
    del options["运输期"]["baseline_source"]
    data["config"]["stability_period_options"] = json.dumps(options, ensure_ascii=False)
    with pytest.raises(InputError, match="须明确登记 baseline_source"):
        calculate(data)


@pytest.mark.parametrize(
    "entry",
    [
        {"stability_method": "regression_trend"},
        {"rule": "wrong"},
        {"unknown": 1},
        {"basis": "wrong"},
        {"delta_e": -1},
    ],
)
def test_invalid_options(entry: dict) -> None:
    data = data_for("gl003", {"运输期": entry})
    with pytest.raises(InputError):
        calculate(data)


def test_expanded_defaults_are_not_misreported_as_global() -> None:
    data = data_for("gbt28043", {})
    data["_diagnostic_config"] = {"criterion_standard": "gbt28043"}
    result = calculate(data)["GB/T稳定性"]["稳定期"]["criterion_settings"]
    assert result["stability_method"] == {"value": "two_sample", "source": "方法默认"}


def test_two_sample_homogeneity_baseline_without_baseline_group() -> None:
    data = data_for(
        "gl003",
        {
            "稳定期": {"stability_method": "two_sample", "baseline_source": "homogeneity"},
            "运输期": {"stability_method": "mean_difference", "baseline_source": "homogeneity"},
        },
    )
    del data["stability"]["基线"]
    result = calculate(data)
    assert result["稳定性"]["method"] == "two_sample"
    assert result["稳定性"]["mean1"] == pytest.approx(
        sum(map(sum, data["homogeneity"])) / sum(map(len, data["homogeneity"]))
    )


def test_missing_baseline_location(tmp_path: Path) -> None:
    book = load_workbook(EXAMPLE)
    sheet = book["方法配置"]
    for row in sheet.iter_rows(min_row=2):
        if "（stability_period_options）" in str(row[0].value):
            row[1].value = '{"稳定期":{"stability_method":"mean_difference"}}'
            position = row[1].coordinate
            break
    for row in sheet.iter_rows(min_row=2):
        if "（criterion_standard）" in str(row[0].value):
            row[1].value = "gl003"
    path = tmp_path / "missing.xlsx"
    book.save(path)
    issues = inspect_input(path)
    assert any(
        i.code == "PERIOD_CRITERIA" and i.cell == position and "须明确登记" in i.message
        for i in issues
    )


def test_unknown_group_and_location(tmp_path: Path) -> None:
    book = load_workbook(EXAMPLE)
    sheet = book["方法配置"]
    for row in sheet.iter_rows(min_row=2):
        if "（stability_period_options）" in str(row[0].value):
            row[1].value = '{"不存在":{"rule":"basic"}}'
            position = row[1].coordinate
            break
    path = tmp_path / "example.xlsx"
    book.save(path)
    issues = inspect_input(path)
    assert any(i.code == "PERIOD_CRITERIA" and i.cell == position for i in issues)
    assert "不存在" in format_error(
        InputError("输入校验问题：" + json.dumps([i.to_dict() for i in issues], ensure_ascii=False))
    )
