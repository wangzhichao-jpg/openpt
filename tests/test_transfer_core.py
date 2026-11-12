# SPDX-License-Identifier: Apache-2.0
"""传递标准各类判据和 En 防重复计入。"""

import math

import pytest

from openpt.core.scores import performance_score
from openpt.core.transfer import assess_point, en_with_stability
from openpt.errors import InputError
from openpt.review.transfer import review_transfer


def test_transfer_window_and_boundary() -> None:
    rows = [
        {"stage": "传递前", "value": -5.0},
        {"stage": "传递中", "value": -0.2},
        {"stage": "传递后", "value": 0.3},
    ]
    rules = [
        {"kind": "fixed", "value": 0.5, "inclusive": True},
        {"kind": "mpev", "value": 1.5, "k": 3, "inclusive": False},
    ]
    result = assess_point(rows, rules, window="transfer_only")
    assert result["delta_max"] == pytest.approx(0.5)
    assert [r["pass"] for r in result["criteria"]] == [True, False]
    row = review_transfer(result, {"name": "Δmax", "value": 0.49, "digits": 2})
    assert row["差异类型"] == "VALUE_MISMATCH" and row["说明"] == "结论受影响"
    unaffected = assess_point(rows, [{"kind": "fixed", "value": 1.0}], window="transfer_only")
    same = review_transfer(unaffected, {"name": "Δmax", "value": 0.4, "digits": 2})
    assert same["说明"] == "结论不受影响"
    assert (
        review_transfer(unaffected, {"name": "限值", "value": 1.0, "digits": 1})["状态"] == "MATCH"
    )
    assert review_transfer(unaffected, {"name": "结论", "value": "不稳定"})["说明"] == "结论受影响"
    with pytest.raises(InputError, match="序号"):
        review_transfer(result, {"name": "限值", "value": 1.0, "digits": 1})
    assert assess_point(rows, rules, window="all")["delta_max"] == pytest.approx(5.3)
    summary = assess_point(
        [], [{"kind": "u_ref", "value": 1, "k": 2, "inclusive": True}], summarized_delta=0.5
    )
    assert summary["conclusion"] is True and summary["count"] is None
    with pytest.raises(InputError):
        assess_point(rows, rules, summarized_delta=0.5)


def test_single_and_two_sample_t() -> None:
    rows = [{"stage": "传递中", "value": n} for n in (1.0, 1.1, 1.2, 1.3)]
    criteria = [
        {"kind": "one_sample", "reference": 1.15},
        {"kind": "two_sample", "baseline": [1.0, 1.1, 1.2, 1.3]},
    ]
    result = assess_point(rows, criteria)
    assert all(rule["pass"] is True for rule in result["criteria"])
    overridden = assess_point(
        rows,
        [
            {
                "kind": "one_sample",
                "reference": 1.15,
                "critical_override": 2.0,
                "critical_source": "报告",
            }
        ],
    )
    assert overridden["criteria"][0]["limit"] == 2.0
    with pytest.raises(InputError, match="来源"):
        assess_point(rows, [{"kind": "one_sample", "reference": 1.15, "critical_override": 2.0}])
    with pytest.raises(InputError):
        assess_point([], criteria, summarized_delta=0.2)


def test_existing_en_score_with_explicit_stability_component() -> None:
    options = {
        "U_assigned": 1.0,
        "U_participant": 1.0,
        "k_assigned": 2.0,
        "k_participant": 2.0,
        "independent": True,
    }
    result = performance_score("En", 1.0, 0.0, U_E=0.4, **options)
    assert result.value == pytest.approx(1 / math.hypot(1, 1, 0.4))
    assert "U_E" in result.formula
    duplicated = performance_score("En", 1.0, 0.0, U_E=0.4, stability_in_U_ref=True, **options)
    assert duplicated.status == "DESIGN_REVIEW" and duplicated.value is None


def test_en_mechanisms_and_review() -> None:
    a = en_with_stability(1.0, 1.0, 1.0, mechanism="A", delta=0.6)
    assert a["u_stab"] == pytest.approx(0.3 / math.sqrt(3))
    assert a["En"] == pytest.approx(1 / math.hypot(1, a["U_ref"]))
    b = en_with_stability(1.0, 1.0, 1.0, mechanism="B", delta=0.2, u_e_multiplier=2)
    assert b["U_E"] == pytest.approx(0.4)
    assert b["En"] == pytest.approx(1 / math.hypot(1, 1, 0.4))
    assert (
        en_with_stability(1, 1, 1, mechanism="A", delta=0.2, u_e=0.4)["status"] == "DESIGN_REVIEW"
    )
    assert (
        en_with_stability(1, 1, 1, mechanism="B", u_e=0.4, ref_includes_stability=True)["status"]
        == "DESIGN_REVIEW"
    )
    assert en_with_stability(1, 1, 1, mechanism="C")["status"] == "DESIGN_REVIEW"
    assert en_with_stability(1, 1, 1, mechanism="C", ignore_condition=True)["status"] == "OK"
