# SPDX-License-Identifier: Apache-2.0
"""GL002 附录 B.2 表 B1 的 S、D 中位数与 NIQR。"""

import pytest

from openpt.core.robust import median_niqr


def test_table_b1_s_d() -> None:
    """输入采用表中已显示的 S、D；精度受中间值修约影响。"""
    s = [
        1.2615,
        1.2997,
        1.3188,
        1.3548,
        1.2495,
        1.3166,
        1.3131,
        1.3004,
        1.3223,
        1.3103,
        1.3089,
        1.2926,
        1.3930,
        1.3110,
        1.3237,
        1.2777,
    ]
    d = [
        0.0495,
        0.0467,
        0.0629,
        0.0523,
        0.0445,
        0.0438,
        0.0530,
        0.0431,
        0.0481,
        0.0318,
        0.0502,
        0.0368,
        0.0495,
        0.0410,
        0.0339,
        0.0559,
    ]
    sr, dr = median_niqr(s), median_niqr(d)
    assert sr.median == pytest.approx(1.3106, abs=0.000051)
    assert dr.median == pytest.approx(0.0474)
    assert sr.niqr == pytest.approx(0.01612, abs=0.00001)
    # 已修约 D 再内插产生两次修约传播，略超过一个末位，故另以 A/B 原值核对。
    assert dr.niqr == pytest.approx(0.00603, abs=0.00002)


def test_table_b1_original_pairs() -> None:
    """GL002 B.2 表 B1：由 A/B 全精度计算 S、D，按显示值一个末位核对。"""
    from math import sqrt

    a = [
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
    b = [
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
    s = median_niqr([(x + y) / sqrt(2) for x, y in zip(a, b, strict=True)])
    d = median_niqr([(x - y) / sqrt(2) for x, y in zip(a, b, strict=True)])
    assert s.median == pytest.approx(1.3106, abs=0.0001)
    assert d.median == pytest.approx(0.0474, abs=0.0001)
    assert s.niqr == pytest.approx(0.01612, abs=0.00001)
    assert d.niqr == pytest.approx(0.00603, abs=0.00001)
