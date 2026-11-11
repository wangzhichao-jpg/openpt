# SPDX-License-Identifier: Apache-2.0
"""相关设计及参考值不确定度的安全阻断。"""

import pytest

from openpt.cli import calculate
from openpt.core.stability import analyze
from openpt.errors import InputError
from openpt.review.compare import review


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


def test_repeats_only_review_mode() -> None:
    """重复层级只供复现，并与单元均值的推荐模型分开。"""
    sample = [[1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 7]]
    data = {
        "config": {"observation_level": "all_repeats"},
        "homogeneity": [],
        "stability": {"基线": sample, "稳定期": [[v + 0.5 for v in row] for row in sample]},
        "participants": [],
        "claims": [{"name": "t", "value": 0, "digits": 1, "source": "虚构"}],
    }
    with pytest.raises(InputError, match="仅供复核"):
        calculate(data)
    result = calculate(data, review_mode=True)
    assert result["稳定性"]["model"] == "unit_pooled"
    assert result["报告层级稳定性"]["model"] == "repeats_pooled"
    rows = review(data, result)
    assert "PSEUDO_REPLICATION" in rows[0]["差异类型"]
