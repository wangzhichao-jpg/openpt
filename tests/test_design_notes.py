# SPDX-License-Identifier: Apache-2.0
"""GL003 抽样设计提示的条款和状态。"""

import pytest

from openpt.core.stability import analyze, summary_t
from openpt.errors import InputError


def test_two_mean_and_difference_design_clauses() -> None:
    """GL003 5.2.2 注和 5.3 注：两组单元数与抽样数分别检查。"""
    result = analyze([[1, 2], [2, 3], [3, 4]], [[1, 2], [2, 3]], sigma=1)
    assert any("GL003 5.2.2 注：n1、n2 均≥6" in item for item in result.design_warnings)
    assert any("GL003 5.3 注：抽样数≥3" in item for item in result.design_warnings)
    assert result.design_status == "DESIGN_WARNING"


def test_one_mean_design_clause() -> None:
    """GL003 5.2.1 注：单均值 t 建议不少于六个观测单位。"""
    result = analyze(None, [[1, 2], [2, 3], [3, 4]], method="one_sample", reference=2)
    assert any("GL003 5.2.1 注：n≥6" in item for item in result.design_warnings)


@pytest.mark.parametrize(
    "baseline,followup,options",
    [
        ([[1], [2, 3]], [[1], [2]], {}),
        ([[1], [2]], [[1]], {}),
        ([[1], [2]], [[1], [2]], {"model": "invalid"}),
        ([[1], [2]], [[1], [2]], {"method": "invalid"}),
        ([[1], [2]], [[1], [2]], {"alpha": 0}),
        ([[1], [2]], [[1], [2]], {"sigma": 0}),
    ],
)
def test_invalid_stability_inputs(baseline, followup, options) -> None:
    """合成异常设计必须以定位类输入错误拒绝。"""
    with pytest.raises(InputError):
        analyze(baseline, followup, **options)


def test_invalid_summary() -> None:
    """自由度不足和非有限汇总量不能参与 t 检验。"""
    with pytest.raises(InputError):
        summary_t(1, 2, 1, 1, 1, 2)
