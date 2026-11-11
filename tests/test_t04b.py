# SPDX-License-Identifier: Apache-2.0
"""不平衡随机效应 ANOVA 的独立手算对照。"""

import math

import pytest

from openpt.core.homogeneity import analyze


def test_unbalanced_hand_calculation() -> None:
    """[1,3] 与 [2,4,6]：总均值 3.2，SSb=4.8，SSw=10。"""
    result = analyze([[1, 3], [2, 4, 6]])
    assert result.mean == pytest.approx(3.2)
    assert result.SS_between == pytest.approx(4.8)
    assert result.SS_within == pytest.approx(10)
    assert result.df_between == 1 and result.df_within == 3
    assert result.n0 == pytest.approx(2.4)
    assert result.MS_between == pytest.approx(4.8)
    assert result.MS_within == pytest.approx(10 / 3)
    assert pytest.approx(1.44) == result.F
    # F(1,3)=t(3)^2；t=1.2 的双尾概率可用三角积分手算。
    theta = math.atan(1.2 / math.sqrt(3))
    manual_p = 1 - (2 * theta + math.sin(2 * theta)) / math.pi
    assert result.p == pytest.approx(manual_p)
    assert result.variance_raw == pytest.approx((4.8 - 10 / 3) / 2.4)
    assert result.design_status == "DESIGN_WARNING"


def test_balanced_effective_count() -> None:
    """平衡时有效重复数退化为每组重复数。"""
    result = analyze([[1, 3], [3, 5]])
    assert result.n0 == 2
    assert pytest.approx(2) == result.F
    assert result.Ss == pytest.approx(1)
