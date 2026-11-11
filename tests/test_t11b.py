# SPDX-License-Identifier: Apache-2.0
"""GL002 4.4.1.3、4.5.1 能力统计量。"""

import math

import pytest

from openpt.core.scores import performance_score


def test_six_statistics() -> None:
    """六项公式按手算对照，ζ、En 声明独立和 k=2。"""
    options = dict(
        sigma=2,
        u_assigned=1,
        u_participant=2,
        U_assigned=2,
        U_participant=4,
        k_assigned=2,
        k_participant=2,
        independent=True,
    )
    expected = {
        "D": 2,
        "D%": 20,
        "z": 1,
        "zprime": 2 / math.sqrt(5),
        "zeta": 2 / math.sqrt(5),
        "En": 2 / math.sqrt(20),
    }
    for kind, value in expected.items():
        r = performance_score(kind, 12, 10, **options)
        assert r.status == "OK" and r.value == pytest.approx(value)
        assert r.warnings and "待核对条款号" in r.warnings[0]


@pytest.mark.parametrize(
    ("value", "expected"), [(2, "满意"), (3, "不满意"), (-2, "满意"), (-3, "不满意"), (2.5, "可疑")]
)
def test_z_boundaries(value: float, expected: str) -> None:
    """GL002 4.5.1.1：2 包含于满意，3 包含于不满意。"""
    assert performance_score("z", value, 0, sigma=1).classification == expected


def test_original_sigma_for_uncertainty_warning() -> None:
    """σ′ 已合成时仍按原 σ_pt 检查 0.3 倍阈值。"""
    r = performance_score("z", 1, 0, sigma=6, sigma_pt_reference=5, u_assigned=1.6)
    assert r.warnings


def test_prerequisites() -> None:
    """缺前提不评价，相关或非 k=2 模型转审核。"""
    assert performance_score("D%", 1, 0).status == "NOT_EVALUATED"
    assert performance_score("z", 1, 0).status == "NOT_EVALUATED"
    assert performance_score("zprime", 1, 0, sigma=1).status == "NOT_EVALUATED"
    assert performance_score("zeta", 1, 0, u_assigned=1).status == "NOT_EVALUATED"
    assert performance_score("En", 1, 0, U_assigned=1, U_participant=1).status == "NOT_EVALUATED"
    assert (
        performance_score("zeta", 1, 0, u_assigned=1, u_participant=1, independent=False).status
        == "DESIGN_REVIEW"
    )
    assert (
        performance_score(
            "En",
            1,
            0,
            U_assigned=1,
            U_participant=1,
            k_assigned=1,
            k_participant=2,
            independent=True,
        ).status
        == "DESIGN_REVIEW"
    )
    assert (
        performance_score(
            "En",
            1,
            0,
            U_assigned=0,
            U_participant=1,
            k_assigned=2,
            k_participant=2,
            independent=True,
        ).classification
        == "满意"
    )
