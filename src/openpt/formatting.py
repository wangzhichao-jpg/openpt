# SPDX-License-Identifier: Apache-2.0
"""用户界面数值显示，不改变计算结果。"""

from decimal import Decimal
from typing import Any


def display_value(value: Any, digits: int = 4, places: int | None = None) -> str:
    """统一显示量值；不修改计算结果。"""
    if value is None:
        return "未计算"
    if places is not None:
        return f"{value:.{places}f}"
    text = f"{value:#.{digits}g}"
    mantissa, separator, exponent = text.partition("e")
    # 普通量级使用定点格式，同时保留有效数字末尾的零。
    if separator and -6 <= int(exponent) < max(6, digits):
        return format(Decimal(text), "f")
    return mantissa.removesuffix(".") + (separator + exponent if separator else "")


def significant(value: Any, digits: int = 6) -> str:
    """按有效数字显示数值，空值显示未计算。"""
    return "未计算" if value is None else f"{value:.{digits}g}"
