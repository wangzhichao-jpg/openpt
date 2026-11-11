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
    assert sr.niqr == pytest.approx(0.01612, abs=0.0001)
    assert dr.niqr == pytest.approx(0.00603, abs=0.0001)
