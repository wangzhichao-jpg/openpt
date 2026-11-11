# SPDX-License-Identifier: Apache-2.0
"""CNAS-GL003:2018 4.2 和 4.3，平衡单因子设计。"""

import math
from typing import Any

import numpy as np
from scipy.stats import f as f_distribution

from ..errors import InputError


def analyze(
    data: Any, sigma: float | None = None, alpha: float = 0.05, strict: bool = False
) -> dict[str, Any]:
    """按 GL003 4.2、4.3 计算 F=MS组间/MS组内 和 Ss。"""
    try:
        a = np.asarray(data, dtype=float)
    except (ValueError, TypeError):
        raise InputError("均匀性数据须为平衡数值矩阵") from None
    if a.ndim != 2 or a.shape[0] < 2 or a.shape[1] < 2 or not np.isfinite(a).all():
        raise InputError("至少需要两个单元、每单元两次有限数值")
    if not 0 < alpha < 1:
        raise InputError("alpha 必须在 0 和 1 之间")
    if sigma is not None and (not math.isfinite(sigma) or sigma <= 0):
        raise InputError("sigma 必须为正有限数")
    g, m = a.shape
    with np.errstate(over="ignore", invalid="ignore"):
        means = a.mean(axis=1)
        grand = float(means.mean())
        ssb = float(m * np.sum((means - grand) ** 2))
        ssw = float(np.sum((a - means[:, None]) ** 2))
    db, dw = g - 1, g * (m - 1)
    msb, msw = ssb / db, ssw / dw
    raw = (msb - msw) / m
    if not all(math.isfinite(v) for v in (ssb, ssw, msb, msw, raw)):
        raise InputError("数据范围导致数值溢出")
    ss = math.sqrt(max(0, raw))
    critical = float(f_distribution.ppf(1 - alpha, db, dw))
    stat = msb / msw if msw else None
    if stat is not None and not math.isfinite(stat):
        stat = None
    fpass = stat < critical if stat is not None else None
    threshold = 0.3 * sigma if sigma is not None else None
    sspass = ss <= threshold if threshold is not None else None
    conclusion = (
        (fpass and sspass if sspass is not None else (False if fpass is False else None))
        if strict
        else fpass
    )
    return {
        "status": "INDETERMINATE" if stat is None else "OK",
        "design_warnings": ["GL003 4.1 样品数不足10"] if g < 10 else [],
        "warnings": (["组间方差估计为负，Ss截零；不代表绝对均匀"] if raw < 0 else [])
        + (["组内方差为零，F不可判定，请检查分辨力"] if stat is None else []),
        "g": g,
        "m": m,
        "means": means.tolist(),
        "mean": grand,
        "SS_between": ssb,
        "SS_within": ssw,
        "df_between": db,
        "df_within": dw,
        "MS_between": msb,
        "MS_within": msw,
        "F": stat,
        "F_critical": critical,
        "p": float(f_distribution.sf(stat, db, dw)) if stat is not None else None,
        "variance_raw": raw,
        "Ss": ss,
        "sigma": sigma,
        "threshold": threshold,
        "F_pass": fpass,
        "Ss_pass": sspass,
        "Ss_status": "OK" if sigma is not None else "NOT_EVALUATED",
        "strict": strict,
        "conclusion": conclusion,
    }
