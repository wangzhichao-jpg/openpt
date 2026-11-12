# SPDX-License-Identifier: Apache-2.0
"""GB/T 28043-2019 附录 B：平衡重复设计的均匀性及独立样品稳定性。"""

import math
from typing import Any

import numpy as np
from scipy.stats import chi2, f

from ..errors import InputError
from .decision import compare


def _matrix(data: Any, label: str) -> Any:
    """验证平衡的有限观测矩阵，不自动排除离群值。"""
    try:
        a = np.asarray(data, dtype=float)
    except (TypeError, ValueError):
        raise InputError(f"{label}必须是平衡数值矩阵") from None
    if a.ndim != 2 or a.shape[0] < 2 or a.shape[1] < 2 or not np.isfinite(a).all():
        raise InputError(f"{label}需要至少两个样品、每样至少两次有限重复测量")
    return a


def homogeneity(data: Any, sigma: float | None) -> dict[str, Any]:
    """按 B.2、B.3 计算基本和扩展判据；不对数据进行离群值删除。"""
    a = _matrix(data, "均匀性")
    if sigma is not None and (not math.isfinite(sigma) or sigma <= 0):
        raise InputError("sigma 必须为正有限数")
    g, m = a.shape
    with np.errstate(over="ignore", invalid="ignore"):
        means = a.mean(axis=1)
        mean = float(means.mean())
        sx2 = float(means.var(ddof=1))
        sw2 = float(np.mean(np.var(a, axis=1, ddof=1)))
        raw = sx2 - sw2 / m
    if not all(math.isfinite(x) for x in (mean, sx2, sw2, raw)):
        raise InputError("均匀性统计量数值溢出")
    sx, sw, ss = math.sqrt(sx2), math.sqrt(sw2), math.sqrt(max(0.0, raw))
    limit = 0.3 * sigma if sigma is not None else None
    basic = compare(ss, limit) <= 0 if limit is not None else None
    # B.2.3 表 B.1 覆盖 7 至 20；表外不以外推替代标准表。
    f1 = float(chi2.ppf(0.95, g - 1) / (g - 1)) if 7 <= g <= 20 else None
    if f1 is None:
        f2 = None
    elif m == 2:
        f2 = float((f.ppf(0.95, g - 1, g) - 1) / 2)
    else:
        # 原文前言更正后 F_m：F 分位数除以 m，未减 1。
        f2 = float(f.ppf(0.95, g - 1, g * (m - 1)) / m)
    try:
        c = (
            f1 * limit**2 + f2 * sw2
            if f1 is not None and f2 is not None and limit is not None
            else None
        )
    except OverflowError:
        raise InputError("均匀性扩展限值数值溢出") from None
    if c is not None and not math.isfinite(c):
        raise InputError("均匀性扩展限值数值溢出")
    extended_limit = math.sqrt(c) if c is not None else None
    extended = compare(ss, extended_limit) <= 0 if extended_limit is not None else None
    warnings = ["B.2.1：趋势及离群值（含 Cochran 检验）需人工审查，不自动剔除"]
    if g < 10:
        warnings.append("B.1.1 d)：少于10个样品，须核实减少样本量的依据")
    if f1 is None:
        warnings.append("B.2.3 表B.1 未列此样品数；扩展判据未评价")
    if sigma is not None and compare(sw, 0.5 * sigma) >= 0:
        warnings.append(
            "B.1.1 b)：样本内标准差达到或超过0.5σ_pt，方法重复性需审核并考虑增加重复次数"
        )
    if raw < 0:
        warnings.append("B.3：样品间方差估计为负，按零处理")
    if basic is False:
        warnings.append(
            "B.2.5：考虑重新制备、将样品间差异计入σ′或指定值不确定度；须审核且防止重复计入"
        )
    return {
        "standard": "gbt28043",
        "reference": "GB/T 28043-2019 B.1-B.3",
        "g": g,
        "m": m,
        "mean": mean,
        "means": means.tolist(),
        "sx": sx,
        "sw": sw,
        "variance_raw": raw,
        "ss": ss,
        "sigma": sigma,
        "basic_limit": limit,
        "basic_pass": basic,
        "f1": f1,
        "f2_or_fm": f2,
        "c": c,
        "extended_limit": extended_limit,
        "extended_pass": extended,
        "repeatability_check": compare(sw, 0.5 * sigma) < 0 if sigma is not None else None,
        "warnings": warnings,
    }


def stability(
    baseline: Any,
    followup: Any,
    sigma: float | None,
    *,
    u1: float | None = None,
    u2: float | None = None,
    independent: bool = True,
) -> dict[str, Any]:
    """按 B.5 评价；B.18 仅在提供两均值独立标准不确定度时计算。"""
    x, y = _matrix(baseline, "稳定性基线"), _matrix(followup, "稳定性后续组")
    if sigma is not None and (not math.isfinite(sigma) or sigma <= 0):
        raise InputError("sigma 必须为正有限数")
    if not isinstance(independent, bool):
        raise InputError("独立性必须为布尔值")
    for value in (u1, u2):
        if value is not None and (not math.isfinite(value) or value < 0):
            raise InputError("均值标准不确定度须为非负有限数")
    with np.errstate(over="ignore", invalid="ignore"):
        mean1, mean2 = float(x.mean()), float(y.mean())
        diff = abs(mean1 - mean2)
    if not all(math.isfinite(v) for v in (mean1, mean2, diff)):
        raise InputError("稳定性均值差数值溢出")
    basic_limit = 0.3 * sigma if sigma is not None else None
    basic = compare(diff, basic_limit) <= 0 if basic_limit is not None and independent else None
    extended_limit = (
        basic_limit + 2 * math.hypot(u1, u2)
        if basic_limit is not None and u1 is not None and u2 is not None and independent
        else None
    )
    if extended_limit is not None and not math.isfinite(extended_limit):
        raise InputError("稳定性扩展限值数值溢出")
    warnings = ["B.4.2.3：确认随机抽样、相同实验室及方法和测量时间；运输效应按 B.6 人工确认"]
    if x.shape[0] != y.shape[0] or x.shape[1] != y.shape[1]:
        warnings.append("B.4.2.3-B.4.2.4：两组样品数或重复数不同；使用历史均匀性数据须人工确认")
    if not independent:
        warnings.append("相关或配对数据不适用独立样品模型，需人工审核")
    if basic is False:
        warnings.append("B.5.3：评估不稳定性影响、改进制备储存或不进行能力评价")
    return {
        "standard": "gbt28043",
        "reference": "GB/T 28043-2019 B.4-B.6",
        "n1": x.shape[0],
        "m1": x.shape[1],
        "n2": y.shape[0],
        "m2": y.shape[1],
        "mean1": mean1,
        "mean2": mean2,
        "difference": diff,
        "sigma": sigma,
        "basic_limit": basic_limit,
        "basic_pass": basic,
        "u1": u1,
        "u2": u2,
        "extended_limit": extended_limit,
        "extended_pass": compare(diff, extended_limit) <= 0 if extended_limit is not None else None,
        "warnings": warnings,
    }
