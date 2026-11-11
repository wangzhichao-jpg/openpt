# SPDX-License-Identifier: Apache-2.0
"""GL002/GL003 判定阈值的十进制网格及边界测试。"""

from decimal import Decimal
from types import SimpleNamespace

import numpy as np
import pytest

from openpt.core import homogeneity, stability
from openpt.core.decision import compare
from openpt.core.scores import performance_score
from openpt.core.zscore import zscore


def test_z_decimal_grid() -> None:
    """对 X=0.1..19.9、五种 σ 及正负 2σ/3σ 逐项检查两条 z 路径。"""
    count = 0
    for tenth in range(1, 200):
        x_ref = Decimal(tenth) / 10
        for sigma in map(Decimal, ("0.1", "0.2", "0.3", "0.7", "1.1")):
            for k, expected in ((2, "满意"), (3, "不满意")):
                for sign in (-1, 1):
                    value = x_ref + sign * k * sigma
                    a, b, c = float(value), float(x_ref), float(sigma)
                    assert zscore(a, b, c).classification == expected
                    assert performance_score("z", a, b, sigma=c).classification == expected
                    count += 1
    assert count == 3980


def test_en_and_composite_score_decimal_grid() -> None:
    """3-4-5 不确定度组合的十进制精确边界，不通过浮点计算构造输入。"""
    count = 0
    for tenth in range(1, 200):
        reference = Decimal(tenth) / 10
        for scale in map(Decimal, ("0.01", "0.02", "0.1")):
            a, b, denominator = 3 * scale, 4 * scale, 5 * scale
            for sign in (-1, 1):
                for swap in (False, True):
                    u1, u2 = (b, a) if swap else (a, b)
                    x = float(reference + sign * denominator)
                    options = dict(
                        U_assigned=float(u1),
                        U_participant=float(u2),
                        k_assigned=2,
                        k_participant=2,
                        independent=True,
                    )
                    assert (
                        performance_score("En", x, float(reference), **options).classification
                        == "满意"
                    )
                    for multiple, expected in ((2, "满意"), (3, "不满意")):
                        x2 = float(reference + sign * multiple * denominator)
                        zp = performance_score(
                            "zprime", x2, float(reference), sigma=float(u1), u_assigned=float(u2)
                        )
                        ze = performance_score(
                            "zeta",
                            x2,
                            float(reference),
                            u_assigned=float(u1),
                            u_participant=float(u2),
                            independent=True,
                        )
                        assert zp.classification == expected and ze.classification == expected
                    count += 1
    assert count == 2388


def test_one_display_unit_around_boundaries() -> None:
    """保留三位小数时，在临界值两侧各差 0.001 的真实越界不得被容差吞掉。"""
    for value, expected in [(1.999, "满意"), (2.001, "可疑"), (2.999, "可疑"), (3.001, "不满意")]:
        assert performance_score("z", value, 0, sigma=1).classification == expected
        assert zscore(value, 0, 1).classification == expected
    for value, expected in [(0.999, "满意"), (1.001, "不满意")]:
        result = performance_score(
            "En",
            value,
            0,
            U_assigned=0.6,
            U_participant=0.8,
            k_assigned=2,
            k_participant=2,
            independent=True,
        )
        assert result.classification == expected
    assert compare(0.3, 0.30000000000000004) == 0
    assert compare(0, 1e-300) == -1
    for kind in ("zprime", "zeta"):
        options = (
            {"sigma": 0.6, "u_assigned": 0.8}
            if kind == "zprime"
            else {"u_assigned": 0.6, "u_participant": 0.8, "independent": True}
        )
        for value, expected in (
            (1.999, "满意"),
            (2.001, "可疑"),
            (2.999, "可疑"),
            (3.001, "不满意"),
        ):
            assert performance_score(kind, value, 0, **options).classification == expected
    assert not performance_score("z", 0, 0, sigma=1, u_assigned=0.30000000000000004).warnings
    assert performance_score("z", 0, 0, sigma=1, u_assigned=0.301).warnings


def test_ss_and_f_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    """GL003 4.2 严格小于，4.3 小于等于；模拟最后一位误差。"""
    original = homogeneity._anova([[1, 2], [2, 3]])
    monkeypatch.setattr(
        homogeneity, "f_distribution", SimpleNamespace(ppf=lambda *args: 2.0, sf=lambda *args: 0.5)
    )
    for ss, expected in ((0.299, True), (0.30000000000000004, True), (0.301, False)):
        values = {**original, "variance_raw": ss * ss, "MS_between": 2.0 + 1e-13, "MS_within": 1.0}
        monkeypatch.setattr(homogeneity, "_anova", lambda data, fixed=values: fixed)
        result = homogeneity.analyze([[1, 2], [2, 3]], sigma=1)
        assert result.Ss_pass is expected
        assert result.F_pass is False


def test_stability_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    """GL003 5.2 严格比较 t，5.3 均值差与阈值比较。"""
    sample = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    reference = stability._one_sample(sample, 0, 0.05)
    two = stability.summary_t(0, 2, 1, 1, 6, 6)
    for method, value in (("one", reference["t"]), ("two", two.t)):
        assert value is not None
        for delta, expected in ((1e-13, False), (0.001, True), (-0.001, False)):
            fake = SimpleNamespace(
                ppf=lambda *args, fixed=value + delta: fixed, sf=lambda *args: 0.25
            )
            monkeypatch.setattr(stability, "t_distribution", fake)
            result = (
                stability._one_sample(sample, 0, 0.05)["pass"]
                if method == "one"
                else stability.summary_t(0, 2, 1, 1, 6, 6).passed
            )
            assert result is expected
    baseline = [[0.6, 0.6], [0.6, 0.6]]
    followup = [[0.8, 0.8], [0.8, 0.8]]
    assert stability.analyze(baseline, followup, sigma=2 / 3).mean_difference_pass is True
    followup = [[0.801, 0.801], [0.801, 0.801]]
    assert stability.analyze(baseline, followup, sigma=2 / 3).mean_difference_pass is False
