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
        {"name": "均值差", "value": 0.56, "digits": 2, "source": "报告"},
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
    assert claims["ȳ"]["状态"] == "MATCH"
    assert claims["x̄"]["状态"] == "DIFFERENCE"
    assert "VALUE_MISMATCH" in claims["x̄"]["差异类型"]
    assert "结论受影响" in claims["x̄"]["说明"]


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
