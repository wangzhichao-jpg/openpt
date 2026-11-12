# SPDX-License-Identifier: Apache-2.0
"""GB/T 28043-2019 附录 B：平衡重复设计的均匀性及独立样品稳定性。"""

import json
import math
from typing import Any

import numpy as np
from scipy.stats import chi2, f

from ..errors import InputError
from ..io.shape import insufficient_homogeneity_replicates, insufficient_units
from .decision import compare


def _matrix(data: Any, label: str) -> Any:
    """验证平衡的有限观测矩阵，不自动排除离群值。"""
    try:
        a = np.asarray(data, dtype=float)
    except (TypeError, ValueError):
        raise InputError(f"{label}必须是平衡数值矩阵") from None
    if (
        a.ndim != 2
        or insufficient_units(a.shape[0])
        or insufficient_homogeneity_replicates(a.shape[1])
        or not np.isfinite(a).all()
    ):
        raise InputError(f"{label}需要至少两个样品、每样至少两次有限重复测量")
    return a


def criterion_limit(
    sigma: float | None, delta_e: float | None = None, basis: str | None = None
) -> tuple[str, float | None]:
    """选择基本判据依据；双输入须明确选择，不静默替换。"""
    for name, value in (("sigma", sigma), ("delta_e", delta_e)):
        try:
            invalid = value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            )
        except OverflowError:
            invalid = True
        if invalid:
            raise InputError(f"{name} 必须为正有限数")
    if basis not in (None, "", "sigma_pt", "delta_e"):
        raise InputError("gbt_criterion_basis 应为 sigma_pt 或 delta_e")
    if not basis:
        if sigma is not None and delta_e is not None:
            raise InputError("同时输入 sigma 和 delta_e 时须选择 gbt_criterion_basis")
        basis = "delta_e" if delta_e is not None else "sigma_pt"
    elif (basis == "sigma_pt" and sigma is None) or (basis == "delta_e" and delta_e is None):
        raise InputError("所选 gbt_criterion_basis 缺少对应输入")
    value = sigma if basis == "sigma_pt" else delta_e
    threshold = (0.3 if basis == "sigma_pt" else 0.1) * value if value is not None else None
    if threshold == 0:
        raise InputError("判据限值数值下溢")
    return basis, threshold


def homogeneity(
    data: Any, sigma: float | None, *, delta_e: float | None = None, basis: str | None = None
) -> dict[str, Any]:
    """按 B.2、B.3 计算基本和扩展判据；不对数据进行离群值删除。"""
    a = _matrix(data, "均匀性")
    basis, limit = criterion_limit(sigma, delta_e, basis)
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
            if f1 is not None and f2 is not None and limit is not None and basis == "sigma_pt"
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
    elif m > 2:
        warnings.append("B.2.3 的 m>2 系数按印刷更正式实现；统计含义及适用性须独立专家复核")
    if basis == "delta_e":
        warnings.append("B.2.3 扩展判据以 σ_pt 表达；δ_E 依据下未评价扩展判据")
    if sigma is not None and compare(sw, 0.5 * sigma) >= 0:
        warnings.append(
            "B.1.1 b)：样本内标准差达到或超过0.5σ_pt，方法重复性需审核并考虑增加重复次数"
        )
    if raw < 0:
        warnings.append("B.3：样品间方差估计为负，按零处理")
    if basic is False:
        warnings.append(
            "基本判据未满足；如预选主判据未通过，按 B.2.5 审核重新制备或分量处置并防止重复计入"
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
        "delta_e": delta_e,
        "criterion_basis": basis,
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


def period_options(config: dict[str, Any], groups: Any) -> dict[str, dict[str, Any]]:
    """解析逐时点类型及标准不确定度；不允许把一个时点的 u2 静默用于其他时点。"""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise InputError("逐时点配置中存在重复键")
            result[key] = value
        return result

    raw = config.get("stability_period_options")
    if raw in (None, ""):
        raw = {}
    elif isinstance(raw, str):
        try:
            raw = json.loads(raw, object_pairs_hook=pairs)
        except (ValueError, TypeError):
            raise InputError("逐时点配置须为有效 JSON 对象且不得有重复键") from None
    if not isinstance(raw, dict) or not all(isinstance(k, str) for k in raw):
        raise InputError("逐时点配置须为对象")
    names = set(groups) - {"基线"}
    if set(raw) - names:
        raise InputError("逐时点配置包含不存在的时间组")
    u1 = config.get("stability_u1")
    global_u2 = config.get("stability_u2")

    def uncertainty(value: Any) -> float | None:
        if value in (None, ""):
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InputError("均值标准不确定度须为非负有限数")
        try:
            number = float(value)
        except OverflowError:
            raise InputError("均值标准不确定度数值溢出") from None
        if not math.isfinite(number) or number < 0:
            raise InputError("均值标准不确定度须为非负有限数")
        return number

    u1 = uncertainty(u1)
    global_u2 = uncertainty(global_u2)
    resolved = {}
    for name in names:
        entry = raw.get(name, {})
        if not isinstance(entry, dict) or set(entry) - {"kind", "u2"}:
            raise InputError("逐时点配置仅支持 kind 和 u2")
        kind = entry.get("kind", "storage")
        if kind not in ("storage", "transport"):
            raise InputError("稳定性类型应为 storage 或 transport")
        if name == "稳定期" and "u2" in entry and global_u2 is not None:
            raise InputError("稳定期不确定度不可同时在两处输入")
        u2 = (
            uncertainty(entry["u2"]) if "u2" in entry else (global_u2 if name == "稳定期" else None)
        )
        resolved[name] = {"kind": kind, "u1": u1, "u2": u2}
    return resolved


def stability(
    baseline: Any,
    followup: Any,
    sigma: float | None,
    *,
    u1: float | None = None,
    u2: float | None = None,
    delta_e: float | None = None,
    basis: str | None = None,
    independent: bool = True,
    kind: str = "storage",
) -> dict[str, Any]:
    """按 B.5 评价；B.18 仅在提供两均值独立标准不确定度时计算。"""
    x, y = _matrix(baseline, "稳定性基线"), _matrix(followup, "稳定性后续组")
    basis, basic_limit = criterion_limit(sigma, delta_e, basis)
    if not isinstance(independent, bool):
        raise InputError("独立性必须为布尔值")
    if kind not in ("storage", "transport"):
        raise InputError("稳定性类型应为 storage 或 transport")
    for value in (u1, u2):
        if value is not None and (not math.isfinite(value) or value < 0):
            raise InputError("均值标准不确定度须为非负有限数")
    with np.errstate(over="ignore", invalid="ignore"):
        mean1, mean2 = float(x.mean()), float(y.mean())
        diff = abs(mean1 - mean2)
        sw1 = float(np.sqrt(np.mean(np.var(x, axis=1, ddof=1))))
        sw2 = float(np.sqrt(np.mean(np.var(y, axis=1, ddof=1))))
    if not all(math.isfinite(v) for v in (mean1, mean2, diff, sw1, sw2)):
        raise InputError("稳定性均值或组内重复性数值溢出")
    basic = compare(diff, basic_limit) <= 0 if basic_limit is not None and independent else None
    extended_limit = (
        basic_limit + 2 * math.hypot(u1, u2)
        if basis == "sigma_pt"
        and basic_limit is not None
        and u1 is not None
        and u2 is not None
        and independent
        else None
    )
    if extended_limit is not None and not math.isfinite(extended_limit):
        raise InputError("稳定性扩展限值数值溢出")
    warnings = ["B.4.2.3：确认随机抽样、相同实验室及方法和测量时间"]
    if kind == "transport":
        warnings.append("B.6：确认基线是未运输对照组、后续组代表运输条件，并记录已知运输影响")
    else:
        warnings.append("B.4.2.2：确认是否包含运输影响；单独检验运输影响时登记 transport 类型")
    if x.shape[0] != y.shape[0] or x.shape[1] != y.shape[1]:
        warnings.append("B.4.2.3-B.4.2.4：两组样品数或重复数不同；使用历史均匀性数据须人工确认")
    repeatability_limit = 0.5 * sigma if sigma is not None else None
    repeatability_exceeded = (
        compare(max(sw1, sw2), repeatability_limit) > 0 if repeatability_limit is not None else None
    )
    if repeatability_exceeded:
        warnings.append("B.4.1.2：组内重复性超过0.5σ_pt，须评估增加样品或重复测量")
    if basis == "delta_e":
        warnings.append("B.5.2 扩展判据以 σ_pt 表达；δ_E 依据下未评价扩展判据")
    if not independent:
        warnings.append("相关或配对数据不适用独立样品模型，需人工审核")
    if basic is False:
        warnings.append("基本判据未满足；如预选主判据未通过，按 B.5.3 审核不稳定性影响及处置")
    return {
        "standard": "gbt28043",
        "reference": "GB/T 28043-2019 B.4.1.2、B.5.1-B.5.2"
        + ("、B.6" if kind == "transport" else ""),
        "kind": kind,
        "n1": x.shape[0],
        "m1": x.shape[1],
        "n2": y.shape[0],
        "m2": y.shape[1],
        "mean1": mean1,
        "mean2": mean2,
        "difference": diff,
        "sw1": sw1,
        "sw2": sw2,
        "repeatability_limit": repeatability_limit,
        "repeatability_exceeded": repeatability_exceeded,
        "sigma": sigma,
        "delta_e": delta_e,
        "criterion_basis": basis,
        "basic_limit": basic_limit,
        "basic_pass": basic,
        "u1": u1,
        "u2": u2,
        "extended_limit": extended_limit,
        "extended_pass": compare(diff, extended_limit) <= 0 if extended_limit is not None else None,
        "warnings": warnings,
    }
