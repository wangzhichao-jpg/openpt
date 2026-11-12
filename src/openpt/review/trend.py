# SPDX-License-Identifier: Apache-2.0
"""趋势声称值的数值复核与内部一致性检查。"""

import math
from typing import Any

from ..errors import InputError
from .compare import display

_NAMES = {
    "b1": "b1",
    "b0": "b0",
    "s(b1)": "s_b1",
    "阈值": "threshold",
    "X̄": "x_bar",
    "Ȳ": "y_bar",
    "t": "t_critical",
}


def review_trend(result: dict[str, Any], claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按声称精度比较，并考虑中间量的显示修约范围。"""
    rows: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    for claim in claims:
        name = claim.get("name")
        if name == "结论":
            if name in by_name:
                raise InputError("趋势声称结论重复")
            value = claim.get("value")
            if value not in ("稳定", "趋势显著"):
                raise InputError("趋势声称结论应为稳定或趋势显著")
            expected_stable = result.get("stable")
            match = None if expected_stable is None else (value == "稳定") is expected_stable
            rows.append(
                {
                    "统计量": "结论",
                    "声称值": value,
                    "重算值": expected_stable,
                    "显示一致": match,
                    "状态": "MATCH" if match else "DIFFERENCE" if match is False else "NOTE",
                    "差异类型": "VALUE_MISMATCH" if match is False else "",
                    "说明": "结论受影响" if match is False else "",
                }
            )
            by_name[name] = claim
            continue
        if name not in _NAMES or name in by_name:
            raise InputError("趋势声称统计量无效或重复")
        value, digits = claim.get("value"), claim.get("digits")
        if (
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
        ):
            raise InputError("趋势声称值须为有限数")
        if isinstance(digits, bool) or not isinstance(digits, int) or not 0 <= digits <= 12:
            raise InputError("趋势声称值小数位须为0至12的整数")
        expected = result.get(_NAMES[name])
        match = (
            display(value, digits) == display(expected, digits) if expected is not None else None
        )
        row = {
            "统计量": name,
            "声称值": value,
            "重算值": expected,
            "显示一致": match,
            "状态": "MATCH" if match else "DIFFERENCE" if match is False else "NOTE",
            "差异类型": "VALUE_MISMATCH" if match is False else "",
            "说明": "",
        }
        rows.append(row)
        by_name[name] = claim

    def uncertainty(name: str) -> float:
        return 0.5 * 10.0 ** -by_name[name]["digits"]

    if all(name in by_name for name in ("b0", "b1", "X̄", "Ȳ")):
        a, b, x, y = (float(by_name[name]["value"]) for name in ("b0", "b1", "X̄", "Ȳ"))
        tolerance = (
            uncertainty("b0")
            + uncertainty("Ȳ")
            + abs(x) * uncertainty("b1")
            + abs(b) * uncertainty("X̄")
            + uncertainty("b1") * uncertainty("X̄")
        )
        if abs(a - (y - b * x)) > tolerance + 1e-12:
            b0_ok = display(a, by_name["b0"]["digits"]) == display(
                result.get("b0"), by_name["b0"]["digits"]
            )
            b1_ok = display(b, by_name["b1"]["digits"]) == display(
                result.get("b1"), by_name["b1"]["digits"]
            )
            diagnosis = (
                "截距与原始数据重算一致，斜率最可能有误"
                if b0_ok and not b1_ok
                else "斜率与原始数据重算一致，截距最可能有误"
                if b1_ok and not b0_ok
                else "须核查声称的截距、斜率及均值"
            )
            rows.append(
                {
                    "统计量": "截距斜率内部一致性",
                    "状态": "DIFFERENCE",
                    "差异类型": "INTERNAL_INCONSISTENT",
                    "说明": diagnosis,
                }
            )
    if all(name in by_name for name in ("t", "s(b1)", "阈值")):
        t, s, threshold = (float(by_name[name]["value"]) for name in ("t", "s(b1)", "阈值"))
        tolerance = (
            uncertainty("阈值")
            + abs(t) * uncertainty("s(b1)")
            + abs(s) * uncertainty("t")
            + uncertainty("t") * uncertainty("s(b1)")
        )
        if abs(threshold - t * s) > tolerance + 1e-12:
            rows.append(
                {
                    "统计量": "阈值内部一致性",
                    "状态": "DIFFERENCE",
                    "差异类型": "INTERNAL_INCONSISTENT",
                    "说明": "声称阈值与 t×s(b1) 不一致，须结合原始数据重算核查",
                }
            )
    return rows
