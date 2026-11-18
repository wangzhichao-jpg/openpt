# SPDX-License-Identifier: Apache-2.0
"""用户界面数值显示，不改变计算结果。"""

from typing import Any


def significant(value: Any, digits: int = 6) -> str:
    """按有效数字显示数值，空值显示未计算。"""
    return "未计算" if value is None else f"{value:.{digits}g}"
