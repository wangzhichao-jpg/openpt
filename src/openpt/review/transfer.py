# SPDX-License-Identifier: Apache-2.0
"""传递标准声称值及最大变差结论影响的独立复核。"""

import math
from typing import Any

from ..core.decision import compare
from ..errors import InputError
from .compare import display


def review_transfer(result: dict[str, Any], claim: dict[str, Any]) -> dict[str, Any]:
    """对比指定统计量；对于最大变差差异按已登记判据判断结论影响。"""
    aliases = {"Δmax": "delta_max", "U_E": "U_E", "u_stab": "u_stab"}
    name = claim.get("name")
    if name == "结论":
        value = claim.get("value")
        if value not in ("稳定", "不稳定"):
            raise InputError("传递标准声称结论应为稳定或不稳定")
        conclusion = result.get("conclusion")
        matched = None if conclusion is None else (value == "稳定") is conclusion
        return {
            "统计量": name,
            "声称值": value,
            "重算值": conclusion,
            "显示一致": matched,
            "状态": "MATCH" if matched else "DIFFERENCE" if matched is False else "NOTE",
            "差异类型": "VALUE_MISMATCH" if matched is False else "",
            "说明": "结论受影响" if matched is False else "",
        }
    if name not in (*aliases, "限值"):
        raise InputError("传递标准声称统计量不支持")
    value, digits = claim.get("value"), claim.get("digits")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InputError("传递标准声称值须为有限数")
    if isinstance(digits, bool) or not isinstance(digits, int) or not 0 <= digits <= 12:
        raise InputError("显示小数位须为0至12的整数")
    if name == "限值":
        rules = result.get("criteria", [])
        index = claim.get("rule_index")
        if index is None and len(rules) == 1:
            index = 0
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(rules):
            raise InputError("多个判据须明确指定对应判据序号")
        actual = rules[index].get("limit")
    else:
        actual = result.get(aliases[name])
    match = display(value, digits) == display(actual, digits) if actual is not None else None
    note = ""
    if match is False and name == "Δmax":
        criteria = result.get("criteria", [])
        if not criteria or any(
            item.get("kind") not in ("fixed", "mpev", "u_ref")
            or item.get("limit") is None
            or item.get("pass") is None
            for item in criteria
        ):
            note = "结论影响未评价"
        else:
            stated = [
                compare(value, item["limit"]) <= 0
                if item["inclusive"]
                else compare(value, item["limit"]) < 0
                for item in criteria
            ]
            calculated = [item["pass"] for item in criteria]
            note = "结论不受影响" if stated == calculated else "结论受影响"
    return {
        "统计量": name,
        "声称值": value,
        "重算值": actual,
        "显示一致": match,
        "状态": "MATCH" if match else "DIFFERENCE" if match is False else "NOTE",
        "差异类型": "VALUE_MISMATCH" if match is False else "",
        "说明": note,
    }
