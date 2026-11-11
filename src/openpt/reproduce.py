# SPDX-License-Identifier: Apache-2.0
"""重现比较基础：递归比较完整 JSON 结果，不运行输入中的任何代码。"""

import math
from typing import Any


def compare_results(expected: Any, actual: Any, path: str = "$", rtol: float = 1e-12) -> list[str]:
    """逐字段比较类型、键、数组及有限数；浮点只允许相对误差，不设绝对容差。"""
    if not math.isfinite(rtol) or rtol < 0:
        raise ValueError("相对容差必须为非负有限数")
    if isinstance(expected, bool) or isinstance(actual, bool):
        return [] if type(expected) is type(actual) and expected == actual else [path]
    if type(expected) is int and type(actual) is int:
        return [] if expected == actual else [path]
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        try:
            left, right = float(expected), float(actual)
        except OverflowError:
            return (
                []
                if type(expected) is int and type(actual) is int and expected == actual
                else [path]
            )
        if not math.isfinite(left) or not math.isfinite(right):
            return [path]
        return [] if math.isclose(left, right, rel_tol=rtol, abs_tol=0.0) else [path]
    if isinstance(expected, dict) and isinstance(actual, dict):
        differences = []
        for key in sorted(expected.keys() | actual.keys()):
            key_path = f"{path}[{key!r}]"
            if key not in expected or key not in actual:
                differences.append(key_path)
            else:
                differences.extend(compare_results(expected[key], actual[key], key_path, rtol))
        return differences
    if isinstance(expected, list) and isinstance(actual, list):
        differences = []
        for index in range(max(len(expected), len(actual))):
            item_path = f"{path}[{index}]"
            if index >= len(expected) or index >= len(actual):
                differences.append(item_path)
            else:
                differences.extend(compare_results(expected[index], actual[index], item_path, rtol))
        return differences
    return [] if type(expected) is type(actual) and expected == actual else [path]
