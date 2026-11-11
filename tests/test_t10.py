# SPDX-License-Identifier: Apache-2.0
"""指定值方法、来源、σ登记和分量映射。"""

import math

import pytest

from openpt.core.assigned import assign_value
from openpt.errors import InputError


@pytest.mark.parametrize("method", ["known", "certified", "reference", "expert_consensus"])
def test_external_value(method: str) -> None:
    """GL002 4.3.1：外部定值及已评定的标准不确定度。"""
    r = assign_value(method, value=10, uncertainty=0.2, source="证据", uncertainty_source="预算")
    assert r.value == 10 and r.u == 0.2 and r.status == "OK"


def test_participant_and_component_mapping() -> None:
    """扩展方法：u=1.25s*/√p，独立分量只合成一次。"""
    r = assign_value(
        "participant_consensus",
        participants=[1, 2, 3, 4],
        consensus_method="median",
        source="结果",
        uncertainty_source="NIQR",
        sigma_temporary=2,
        sigma_final=3,
        sigma_procedure="预先规定",
        u_hom=0.5,
        hom_mapping="assigned",
        u_stab=0.4,
        stab_mapping="sigma_prime",
    )
    expected = 1.25 * (0.7413 * 1.5) / 2
    assert r.value == 2.5 and r.u == pytest.approx(math.hypot(expected, 0.5))
    assert r.sigma_prime == pytest.approx(math.hypot(3, 0.4))
    for mapping, included in [("both", False), ("sigma_prime", True), ("assigned", True)]:
        bad = assign_value(
            "known",
            value=1,
            uncertainty=0.2,
            source="s",
            uncertainty_source="u",
            u_hom=0.1,
            hom_mapping=mapping,
            hom_in_base=included,
        )
        assert bad.status == "DESIGN_REVIEW" and bad.u is None


def test_missing_uncertainty_and_procedure() -> None:
    """不得用未披露的外部定值不确定度或未登记程序代替。"""
    with pytest.raises(InputError):
        assign_value("certified", value=1, source="s", uncertainty_source="u")
    with pytest.raises(InputError):
        assign_value(
            "known", value=1, uncertainty=0, source="s", uncertainty_source="u", sigma_final=1
        )
