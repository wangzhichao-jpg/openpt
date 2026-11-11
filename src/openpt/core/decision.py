# SPDX-License-Identifier: Apache-2.0
"""统计判据的统一浮点边界比较；不改变原始计算值。"""

import math

from ..errors import InputError

# 项目约定：仅用于临界值判定的相对容差，见 ADR-002。
DECISION_REL_TOLERANCE = 1e-12


def compare(left: float, right: float) -> int:
    """相对误差不大于 1e-12 视为相等；否则返回 -1 或 1。"""
    if not math.isfinite(left) or not math.isfinite(right):
        raise InputError("判据比较值必须有限")
    if math.isclose(left, right, rel_tol=DECISION_REL_TOLERANCE, abs_tol=0.0):
        return 0
    return -1 if left < right else 1
