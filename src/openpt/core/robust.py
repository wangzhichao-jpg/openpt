# SPDX-License-Identifier: Apache-2.0
"""CNAS-GL002:2018 附录 A.2，算法 A。"""

import math
from decimal import Decimal, localcontext
from typing import Any

import numpy as np

from ..errors import InputError
from .models import AlgorithmAResult

# CNAS-GL002:2018 附录 A.2，式 A.2、A.3、A.6。
MAD_FACTOR = 1.483
ALG_A_CLIP = 1.5
ALG_A_SD_FACTOR = 1.134
# 稳健指定值标准不确定度的约定计算因子。
UNCERTAINTY_FACTOR = 1.25


def _gl002_stable(x: float, s: float, next_x: float, next_s: float) -> bool:
    """比较 s 的第三位有效数字及 x 相应位，依据 GL002 附录 A.2。"""
    if next_s == 0:
        return s == 0 and x == next_x
    exponent = Decimal(str(next_s)).adjusted() - 2
    quantum = Decimal(1).scaleb(exponent)
    with localcontext() as context:
        context.prec = 1024
        return Decimal(str(s)).quantize(quantum) == Decimal(str(next_s)).quantize(
            quantum
        ) and Decimal(str(x)).quantize(quantum) == Decimal(str(next_x)).quantize(quantum)


def _iterate(
    data: Any, x: float, s: float, rule: str, tolerance: float, max_iterations: int
) -> tuple[float, float, bool, list[dict[str, Any]]]:
    """按选定规则迭代 GL002 附录 A.2 的截尾和修正公式。"""
    history: list[dict[str, Any]] = []
    converged = rule == "simplified"
    for i in range(0 if rule == "simplified" else max_iterations):
        with np.errstate(over="ignore", invalid="ignore"):
            clipped = np.clip(data, x - ALG_A_CLIP * s, x + ALG_A_CLIP * s)
            nx = float(clipped.mean())
            ns = float(ALG_A_SD_FACTOR * np.std(clipped, ddof=1))
        if not math.isfinite(nx) or not math.isfinite(ns):
            raise InputError("数值溢出")
        history.append({"iteration": i + 1, "x": nx, "s": ns})
        stable = (
            _gl002_stable(x, s, nx, ns) and i > 0
            if rule == "gl002"
            else abs(nx - x) <= tolerance and abs(ns - s) <= tolerance
        )
        x, s = nx, ns
        if stable:
            converged = True
            break
    return x, s, converged, history


def algorithm_a(
    values: Any,
    tolerance: float = 1e-10,
    max_iterations: int = 1000,
    simplified: bool = False,
    rule: str = "gl002",
) -> AlgorithmAResult:
    """按 GL002 附录 A.2 用中位数及截尾数据计算稳健均值、标准差。"""
    try:
        a = np.asarray(values, dtype=float)
    except (ValueError, TypeError):
        raise InputError("参加者结果必须为有限数值") from None
    if a.ndim != 1 or len(a) < 2 or not np.isfinite(a).all():
        raise InputError("至少两个有限参加者结果")
    if (
        not math.isfinite(tolerance)
        or tolerance <= 0
        or not isinstance(max_iterations, int)
        or max_iterations < 1
    ):
        raise InputError("无效迭代参数")
    if rule not in ("gl002", "absolute", "simplified"):
        raise InputError("算法 A 停止规则无效")
    if simplified:
        rule = "simplified"
    with np.errstate(over="ignore", invalid="ignore"):
        x = float(np.median(a))
        s = float(MAD_FACTOR * np.median(np.abs(a - x)))
    if not math.isfinite(x) or not math.isfinite(s):
        raise InputError("稳健统计初始值数值溢出")
    x, s, converged, history = _iterate(a, x, s, rule, tolerance, max_iterations)
    result: dict[str, Any] = {
        "x": x,
        "s": s,
        "u_x": s * (UNCERTAINTY_FACTOR / math.sqrt(len(a))),
        "n": len(a),
        "iterations": len(history),
        "converged": converged,
        "status": "NOT_CONVERGED" if not converged else "INDETERMINATE" if s == 0 else "OK",
        "warning": "稳健尺度为零，需检查重复值与分辨力" if s == 0 else None,
        "simplified": rule == "simplified",
        "rule": rule,
        "tolerance": tolerance,
        "history": history,
    }
    return AlgorithmAResult(**result)
