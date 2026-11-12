# SPDX-License-Identifier: Apache-2.0
"""CNAS-GL002:2018 附录 A.2，算法 A。"""

import math
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any

import numpy as np

from ..config.catalog import ENUMS
from ..errors import InputError
from ..io.shape import insufficient_units
from .models import AlgorithmAResult, AlgorithmSResult, MedianIqrResult

# CNAS-GL002:2018 附录 A.2，式 A.2、A.3、A.6。
MAD_FACTOR = 1.483
ALG_A_CLIP = 1.5
ALG_A_SD_FACTOR = 1.134
# 稳健指定值标准不确定度的约定计算因子。
UNCERTAINTY_FACTOR = 1.25
# CNAS-GL002:2018 附录 A.4，式 A.13。
NIQR_FACTOR = 0.7413
# 算法 S 的绝对容差收敛对照，软件附加规则，见 ADR-002。
S_REFERENCE_TOLERANCE = 1e-12
S_REFERENCE_RELATIVE_TOLERANCE = 1e-12
S_REFERENCE_MAX_ITERATIONS = 10000
# GL002 附录 A.3 表 A.1，依次为自由度 1 至 10 的 (η, ξ)。
ALGORITHM_S_FACTORS = (
    (1.645, 1.097),
    (1.517, 1.054),
    (1.444, 1.039),
    (1.395, 1.032),
    (1.359, 1.027),
    (1.332, 1.024),
    (1.310, 1.021),
    (1.292, 1.019),
    (1.277, 1.018),
    (1.264, 1.017),
)


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
        if rule == "gl002":
            stable = _gl002_stable(x, s, nx, ns) and i > 0
        elif rule == "gbt28043":
            stable = (
                i > 0
                and _three_significant(x) == _three_significant(nx)
                and _three_significant(s) == _three_significant(ns)
            )
        else:
            stable = abs(nx - x) <= tolerance and abs(ns - s) <= tolerance
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
    """算法 A；可选 GB/T 28043-2019 C.3.1 的各自三位有效数字停止规则。"""
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
    if rule not in ENUMS["algorithm_a_rule"]:
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


def _iterate_s(
    data: Any,
    eta: float,
    xi: float,
    initial: float,
    rule: str,
    tolerance: float,
    maximum: int,
    relative_tolerance: float | None = None,
) -> tuple[float, bool, list[dict[str, Any]]]:
    """GL002 附录 A.3 式 A.8—A.10，迭代并记录截断值及联合值。"""
    w = initial
    history: list[dict[str, Any]] = []
    for i in range(maximum):
        limit = eta * w
        if not math.isfinite(limit):
            raise InputError("算法 S 截断值溢出")
        clipped = np.minimum(data, limit)
        new_w = xi * (math.hypot(*clipped) / math.sqrt(len(data)))
        if not math.isfinite(new_w):
            raise InputError("算法 S 结果溢出")
        history.append({"iteration": i + 1, "w": new_w, "limit": limit})
        change = abs(new_w - w)
        stable = (
            _gl002_stable(0, w, 0, new_w) and i > 0
            if rule == "gl002"
            else change <= tolerance
            and (
                relative_tolerance is None or change <= relative_tolerance * max(abs(w), abs(new_w))
            )
        )
        w = new_w
        if stable:
            return w, True, history
    return w, False, history


def _three_significant(value: float) -> Decimal:
    """按各自数值量级用十进制半偶舍入比较，不改动计算值。"""
    if value == 0:
        return Decimal(0)
    decimal = Decimal(str(value))
    quantum = Decimal(1).scaleb(decimal.adjusted() - 2)
    with localcontext() as context:
        context.prec = 1024
        context.rounding = ROUND_HALF_EVEN
        return decimal.quantize(quantum)


def algorithm_s(
    values: Any,
    df: int,
    max_iterations: int = 1000,
    stop_rule: str = "gl002",
    tolerance: float = S_REFERENCE_TOLERANCE,
) -> AlgorithmSResult:
    """GL002 附录 A.3 式 A.7—A.10；另算绝对容差收敛对照。"""
    try:
        data = np.asarray(values, dtype=float)
    except (ValueError, TypeError):
        raise InputError("算法 S 数据必须为有限数") from None
    if (
        data.ndim != 1
        or insufficient_units(len(data))
        or not np.isfinite(data).all()
        or (data < 0).any()
    ):
        raise InputError("算法 S 需要至少两个非负有限标准差或极差")
    if isinstance(df, bool) or not isinstance(df, int) or not 1 <= df <= 10:
        raise InputError("算法 S 自由度必须为 1 至 10")
    if (
        isinstance(max_iterations, bool)
        or not isinstance(max_iterations, int)
        or max_iterations < 1
    ):
        raise InputError("算法 S 最大迭代次数无效")
    if stop_rule not in ENUMS["algorithm_s_stop_rule"]:
        raise InputError("算法 S 停止规则无效")
    if (
        isinstance(tolerance, bool)
        or not isinstance(tolerance, (float, int))
        or not math.isfinite(tolerance)
        or tolerance <= 0
    ):
        raise InputError("算法 S 收敛容差无效")
    eta, xi = ALGORITHM_S_FACTORS[df - 1]
    with np.errstate(over="ignore", invalid="ignore"):
        initial = float(np.median(data))
    if not math.isfinite(initial):
        raise InputError("算法 S 初始值溢出")
    w, converged, history = _iterate_s(data, eta, xi, initial, stop_rule, tolerance, max_iterations)
    ref, ref_converged, ref_history = _iterate_s(
        data,
        eta,
        xi,
        initial,
        "absolute",
        S_REFERENCE_TOLERANCE,
        max(S_REFERENCE_MAX_ITERATIONS, max_iterations),
        relative_tolerance=S_REFERENCE_RELATIVE_TOLERANCE,
    )
    warnings = []
    if not ref_converged:
        warnings.append("REFERENCE_NOT_CONVERGED")
    elif _three_significant(w) != _three_significant(ref):
        warnings.append("STOP_RULE_SENSITIVITY")
    return AlgorithmSResult(
        w=w,
        df=df,
        eta=eta,
        xi=xi,
        iterations=len(history),
        converged=converged,
        status="NOT_CONVERGED" if not converged else "INDETERMINATE" if w == 0 else "OK",
        history=history,
        stop_rule=stop_rule,
        tolerance=tolerance,
        reference_w=ref,
        reference_converged=ref_converged,
        reference_iterations=len(ref_history),
        reference_tolerance=S_REFERENCE_TOLERANCE,
        reference_relative_tolerance=S_REFERENCE_RELATIVE_TOLERANCE,
        warnings=warnings,
    )


def median_niqr(values: Any) -> MedianIqrResult:
    """按 GL002 A.4 计算中位数、四分位距和 NIQR=0.7413×IQR。"""
    try:
        data = np.asarray(values, dtype=float)
    except (ValueError, TypeError):
        raise InputError("参加者结果必须为有限数值") from None
    if data.ndim != 1 or len(data) < 2 or not np.isfinite(data).all():
        raise InputError("至少两个有限参加者结果")
    with np.errstate(over="ignore", invalid="ignore"):
        median = float(np.median(data))
        q1, q3 = (float(x) for x in np.quantile(data, [0.25, 0.75], method="linear"))
        iqr = q3 - q1
        niqr = NIQR_FACTOR * iqr
    if not all(math.isfinite(v) for v in (median, q1, q3, iqr, niqr)):
        raise InputError("四分位统计量数值溢出")
    return MedianIqrResult(median=median, q1=q1, q3=q3, iqr=iqr, niqr=niqr, status="OK")
