# SPDX-License-Identifier: Apache-2.0
"""GL002 附录 A.2 与可选交叉核对。"""

from decimal import ROUND_HALF_UP, Decimal

import pytest

from openpt.core.robust import algorithm_a, median_niqr


def test_u10_gl002_against_optional_library() -> None:
    """GL002 A.2：第三有效位及对应数位；合成对称样本均值为 2。"""
    values = [1.0, 2.0, 3.0, 4.0, 0.0]
    local = algorithm_a(values)
    assert local["rule"] == "gl002"
    assert local["x"] == pytest.approx(2.0)
    library = pytest.importorskip("pt13528.robust")
    reference = library.algorithm_a(values, tol="equivalent-figure")
    assert local["iterations"] == reference.iterations
    assert local["x"] == pytest.approx(reference.location, abs=1e-12)
    assert local["s"] == pytest.approx(reference.scale, abs=1e-12)


def test_gl002_annex_b1_numeric_example() -> None:
    """GL002 附录 B.2 表 B1：中位数及 NIQR；四分位数采用线性插值。"""
    sample_a = [
        0.927,
        0.952,
        0.977,
        0.995,
        0.915,
        0.962,
        0.966,
        0.950,
        0.969,
        0.949,
        0.961,
        0.940,
        1.020,
        0.956,
        0.960,
        0.943,
    ]
    sample_b = [
        0.857,
        0.886,
        0.888,
        0.921,
        0.852,
        0.900,
        0.891,
        0.889,
        0.901,
        0.904,
        0.890,
        0.888,
        0.950,
        0.898,
        0.912,
        0.864,
    ]
    a, b = median_niqr(sample_a), median_niqr(sample_b)
    assert Decimal(str(a.median)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP) == Decimal(
        "0.958"
    )
    assert Decimal(str(b.median)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP) == Decimal(
        "0.891"
    )
    assert round(a.niqr, 4) == 0.0143
    assert round(b.niqr, 4) == 0.0106


def test_absolute_and_simplified() -> None:
    """GL002 附录 A.2 给出简化法；绝对容差为软件附加选项。"""
    values = [0.0, 1.0, 2.0, 3.0, 4.0]
    assert algorithm_a(values, rule="simplified")["iterations"] == 0
    assert algorithm_a(values, rule="absolute", tolerance=1e-9)["converged"]
