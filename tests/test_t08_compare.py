# SPDX-License-Identifier: Apache-2.0
"""重现比较基础的递归与容差测试。"""

import math

from hypothesis import given
from hypothesis import strategies as st

from openpt.reproduce import compare_results


def test_comparison_nested_and_nonfinite() -> None:
    """严格区分布尔值、缺项和整数，浮点只用相对容差。"""
    assert compare_results({"x": [1.0, 0]}, {"x": [1 + 5e-13, 0]}) == []
    assert compare_results({"x": [1.0, 0]}, {"x": [1 + 5e-11, 1e-20]}) == ["$['x'][0]", "$['x'][1]"]
    assert compare_results(2**53, 2**53 + 1) == ["$"]
    assert compare_results(True, 1) == ["$"]
    assert compare_results({"a": 1}, {"b": 1}) == ["$['a']", "$['b']"]
    assert compare_results(math.nan, math.nan) == ["$"]


@given(st.floats(allow_nan=False, allow_infinity=False))
def test_finite_number_matches_itself(number: float) -> None:
    """有限浮点数自身始终一致。"""
    assert compare_results(number, number) == []
