# SPDX-License-Identifier: Apache-2.0
"""GL003 5.3 均值差法及声称值。"""

import pytest

from openpt.cli import calculate
from openpt.core.stability import analyze
from openpt.errors import InputError
from openpt.review.compare import review


def _data() -> dict:
    return {
        "config": {"sigma": 3.0, "stability_method": "mean_difference"},
        "homogeneity": [[37.0, 37.08], [37.0, 37.08], [37.0, 37.08]],
        "stability": {
            "稳定期": [[37.6, 37.6], [37.6, 37.6], [37.6, 37.6]],
            "后期": [[37.1, 37.1], [37.1, 37.1], [37.1, 37.1]],
        },
        "participants": [],
        "claims": [],
    }


def test_homogeneity_default_each_period_and_claims() -> None:
    data = _data()
    data["claims"] = [
        {"name": "均值差", "value": 0.96, "digits": 2, "source": "报告"},
        {"name": "x̄", "value": 36.64, "digits": 2, "source": "报告"},
        {"name": "ȳ", "value": 37.1, "digits": 1, "source": "报告", "timegroup": "后期"},
    ]
    result = calculate(data)
    s = result["稳定性"]
    assert s["difference"] == pytest.approx(0.56)
    assert s["mean_difference_pass"] is True and s["pass"] is None
    assert not s["design_warnings"]
    assert result["其他稳定性"]["后期"]["difference"] == pytest.approx(0.06)
    claims = {row["统计量"]: row for row in review(data, result)}
    assert claims["均值差"]["状态"] == "MATCH"
    assert claims["均值差"]["推荐一致"] is False
    assert claims["ȳ"]["状态"] == "MATCH"
    assert claims["x̄"]["状态"] == "DIFFERENCE"
    assert "VALUE_MISMATCH" in claims["x̄"]["差异类型"]
    assert "结论受影响" in claims["x̄"]["说明"]


def test_reported_means_reproduce_claim_but_keep_recommended_value() -> None:
    data = _data()
    data["claims"] = [
        {
            "name": "稳定性均值差",
            "value": 0.96,
            "digits": 2,
            "source": "报告",
            "timegroup": "稳定期",
        },
        {"name": "x̄", "value": 36.64, "digits": 2, "source": "报告"},
        {"name": "ȳ", "value": 37.60, "digits": 2, "source": "报告", "timegroup": "稳定期"},
    ]
    rows = {row["统计量"]: row for row in review(data, calculate(data))}
    assert rows["稳定性均值差"]["状态"] == "MATCH"
    assert rows["稳定性均值差"]["显示一致"] is True
    assert rows["稳定性均值差"]["推荐一致"] is False
    assert "推荐基线" in rows["稳定性均值差"]["说明"]
    assert rows["稳定性均值差（推荐基线）"]["状态"] == "NOTE"
    assert "MODEL_SWITCH" in rows["稳定性均值差（推荐基线）"]["差异类型"]
    assert rows["x̄"]["状态"] == "DIFFERENCE"


def test_chinese_f_aliases_and_spaced_threshold() -> None:
    data = _data()
    result = calculate(data)
    data["claims"] = [
        {"name": "F值", "value": result["均匀性"]["F"], "digits": 2, "source": "报告"},
        {"name": "方差分析F值", "value": result["均匀性"]["F"], "digits": 2, "source": "报告"},
        {"name": "0.3σ 阈值", "value": 0.9, "digits": 1, "source": "报告"},
    ]
    rows = review(data, result)
    assert all(row["状态"] == "MATCH" for row in rows)
    assert all(row["评分条目"] == "均匀性与稳定性评估" for row in rows)


def test_optional_t_is_reference_only() -> None:
    data = _data()
    baseline = [[1.0, 1.1], [2.0, 2.1], [3.0, 3.1]]
    data["stability"]["基线"] = baseline
    selected = calculate(data)["稳定性"]
    reference = analyze(baseline, data["stability"]["稳定期"], 3.0)
    assert selected["t"] == pytest.approx(reference.t)
    assert selected["t_reference_baseline_mean"] == pytest.approx(reference.mean1)
    assert selected["t_reference_baseline_source"] == "稳定性表基线"
    assert selected["pass"] is None
    assert selected["mean_difference_pass"] is True
    assert not any("5.2" in warning for warning in selected["design_warnings"])


def test_named_periods_without_reserved_followup_group() -> None:
    data = _data()
    data["stability"] = {"7月": data["stability"]["稳定期"], "6月": data["stability"]["后期"]}
    data["claims"] = [
        {"name": "均值差", "value": 0.56, "digits": 2, "source": "报告", "timegroup": "7月"},
        {"name": "均值差", "value": 0.06, "digits": 2, "source": "报告", "timegroup": "6月"},
    ]
    result = calculate(data)
    assert result["稳定性时间组"] == "7月"
    assert result["稳定性"]["difference"] == pytest.approx(0.56)
    assert result["其他稳定性"]["6月"]["difference"] == pytest.approx(0.06)
    assert all(row["状态"] == "MATCH" for row in review(data, result))


def test_baseline_override_and_gbt() -> None:
    data = _data()
    data["config"].update({"baseline_source": "baseline_group", "criterion_standard": "gbt28043"})
    data["stability"]["基线"] = [[37.3, 37.3], [37.3, 37.3], [37.3, 37.3]]
    result = calculate(data)
    assert result["稳定性"]["difference"] == pytest.approx(0.3)
    assert result["GB/T稳定性"]["稳定期"]["difference"] == pytest.approx(0.3)
    data["config"]["baseline_source"] = "homogeneity"
    result = calculate(data)
    assert result["GB/T稳定性"]["稳定期"]["difference"] == pytest.approx(0.56)


def test_boundary_and_design_warning() -> None:
    result = analyze(None, [[0.3, 0.3], [0.3, 0.3]], 1, method="mean_difference", reference=0)
    assert result.mean_difference_pass is True
    assert any("5.3" in warning for warning in result.design_warnings)
    assert not any("n≥6" in warning for warning in result.design_warnings)
    with pytest.raises(InputError):
        analyze(None, [[1, 1], [2, 2]], 1, method="mean_difference")


def test_report_method_switch_suppresses_inapplicable_warning() -> None:
    data = _data()
    data["config"].update(
        {"stability_method": "two_sample", "report_stability_method": "mean_difference"}
    )
    data["stability"]["基线"] = data["homogeneity"]
    rows = review(data, calculate(data))
    assert any("MODEL_SWITCH" in row["差异类型"] for row in rows)
    assert not any("5.2.2 注" in row["说明"] for row in rows)
