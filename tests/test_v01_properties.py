# SPDX-License-Identifier: Apache-2.0
"""新计算函数的有限随机数据退化与溢出测试。"""

import contextlib
import math
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from openpt.core.assigned import assign_value
from openpt.core.homogeneity import analyze
from openpt.core.robust import algorithm_s, median_niqr
from openpt.core.scores import performance_score
from openpt.errors import InputError

finite = st.floats(allow_nan=False, allow_infinity=False, width=64)
nonnegative = st.floats(min_value=0, allow_nan=False, allow_infinity=False, width=64)


def assert_finite(value: Any) -> None:
    """检查结果结构中所有浮点数有限。"""
    if isinstance(value, float):
        assert math.isfinite(value)
    elif isinstance(value, dict):
        for item in value.values():
            assert_finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            assert_finite(item)


@given(st.lists(st.lists(finite, min_size=2, max_size=5), min_size=2, max_size=5))
@settings(max_examples=150, deadline=None)
def test_unbalanced_finite(groups: list[list[float]]) -> None:
    """扩展方法：有限不平衡输入仅允许返回有限结果或 InputError。"""
    with contextlib.suppress(InputError):
        assert_finite(analyze(groups).to_dict())


@given(st.lists(nonnegative, min_size=2, max_size=8), st.integers(1, 10))
@settings(max_examples=150, deadline=None)
def test_s_and_niqr_finite(values: list[float], df: int) -> None:
    """GL002 A.3/A.4：退化尺度和极端有限输入。"""
    for calculation in (lambda: algorithm_s(values, df, 20), lambda: median_niqr(values)):
        with contextlib.suppress(InputError):
            assert_finite(calculation().to_dict())


@given(
    finite,
    finite,
    nonnegative,
    nonnegative,
    st.sampled_from(["D", "D%", "z", "zprime", "zeta", "En"]),
)
@settings(max_examples=250, deadline=None)
def test_scores_finite(x: float, assigned: float, a: float, b: float, kind: str) -> None:
    """GL002 4.4.1.3：不输出 NaN，也不泄漏其他数值异常。"""
    try:
        result = performance_score(
            kind,
            x,
            assigned,
            sigma=a,
            u_assigned=b,
            u_participant=a,
            U_assigned=b,
            U_participant=a,
            k_assigned=2,
            k_participant=2,
            independent=True,
        )
        assert_finite(result.to_dict())
    except InputError:
        pass


@given(
    finite,
    nonnegative,
    nonnegative,
    nonnegative,
    st.sampled_from(["none", "assigned", "sigma_prime", "both"]),
)
@settings(max_examples=150, deadline=None)
def test_assigned_finite(x: float, u: float, hom: float, stab: float, mapping: str) -> None:
    """GL002 4.3.1：映射和不确定度合成的数值边界。"""
    try:
        result = assign_value(
            "known",
            value=x,
            uncertainty=u,
            source="合成",
            uncertainty_source="合成",
            u_hom=hom,
            u_stab=stab,
            hom_mapping=mapping,
        )
        assert_finite(result.to_dict())
    except InputError:
        pass


@given(st.lists(finite, min_size=2, max_size=6))
@settings(max_examples=100, deadline=None)
def test_expert_and_participant_consensus_finite(values: list[float]) -> None:
    """公议均值及稳健公议的极端输入只能有有限结果或 InputError。"""
    for method, options in (
        ("expert_consensus", {"expert_values": values}),
        ("participant_consensus", {"participants": values}),
    ):
        with contextlib.suppress(InputError):
            assert_finite(
                assign_value(method, source="合成", uncertainty_source="合成", **options).to_dict()
            )
