# SPDX-License-Identifier: Apache-2.0
"""数值边界的性质测试。"""

import json

from hypothesis import given, settings
from hypothesis import strategies as st

from openpt.core.homogeneity import analyze
from openpt.errors import InputError


@settings(max_examples=250, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.floats(allow_nan=False, allow_infinity=False, width=64),
            st.floats(allow_nan=False, allow_infinity=False, width=64),
        ),
        min_size=2,
        max_size=12,
    )
)
def test_random_balanced_matrices_no_nonfinite(rows: list[tuple[float, float]]) -> None:
    """合成任意有限矩阵；结果须可编码为严格 JSON 或给出输入错误。"""
    try:
        result = analyze(rows)
    except InputError:
        return
    json.dumps(result, allow_nan=False)


@given(st.floats(allow_nan=False, allow_infinity=False, width=64))
@settings(max_examples=100, deadline=None)
def test_constant_matrix_no_nonfinite(value: float) -> None:
    """人工构造常数矩阵；不可计算时只能报告输入错误。"""
    try:
        result = analyze([[value, value]] * 10)
    except InputError:
        return
    json.dumps(result, allow_nan=False)
