# SPDX-License-Identifier: Apache-2.0
"""趋势拟合的合成数据和设计边界。"""

import math

import pytest

from openpt.core.trend import fit, fit_series, stability_uncertainty
from openpt.errors import InputError


def test_trend_fit_and_limits() -> None:
    r = fit([0, 1, 2, 3], [1, 2, 3, 4.1])
    assert r["b1"] == pytest.approx(1.03)
    assert r["b0"] == pytest.approx(0.98)
    assert r["n"] == 4 and r["df"] == 2 and r["stable"] is False
    assert r["confidence_interval"][0] < r["b1"] < r["confidence_interval"][1]
    assert fit([0, 1, 2], [1, 1.2, 0.9])["design_status"] == "DESIGN_WARNING"
    assert fit([0, 1, 2], [1, 1, 1])["status"] == "INDETERMINATE"
    for x, y in (([0, 1], [1, 2]), ([1, 1, 1], [1, 2, 3]), ([0, 1, 2], [1, 2])):
        with pytest.raises(InputError):
            fit(x, y)


def test_trend_time_mean_and_uncertainty() -> None:
    rows = [
        {"series": name, "time_unit": "天", "x": x, "y": x + shift}
        for name, shift in (("a", 0), ("b", 2))
        for x in (0, 1, 2)
    ]
    result = fit_series(rows, "time_mean")["时间均值"]
    assert result["b0"] == pytest.approx(1)
    assert result["b1"] == pytest.approx(1)
    assert len(fit_series(rows)) == 2
    with pytest.raises(InputError):
        fit_series(rows[:-1], "time_mean")
    with pytest.raises(InputError):
        fit_series(rows + rows[:1])
    result_u = stability_uncertainty(0.1, 14, 0.02, 60)
    assert result_u["u_stab"] == pytest.approx(math.hypot(1.4, 1.2))
    with pytest.raises(InputError):
        stability_uncertainty(-0.1, 14, 0.02, 60)
