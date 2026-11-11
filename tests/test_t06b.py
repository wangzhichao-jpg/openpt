# SPDX-License-Identifier: Apache-2.0
"""相关设计及参考值不确定度的安全阻断。"""

from openpt.core.stability import analyze


def test_design_review_no_conclusion() -> None:
    """GL003 5.2 的独立性或参考值条件不满足时不作判断。"""
    sample = [[1, 2], [2, 3], [3, 4]]
    for options in (
        {"design": "paired"},
        {"design": "correlated"},
        {"reference_uncertainty_negligible": False},
    ):
        result = analyze(sample, sample, sigma=1, **options)
        assert result.status == "DESIGN_REVIEW"
        assert result.t is None and result.passed is None
        assert result.mean_difference_pass is None
