# SPDX-License-Identifier: Apache-2.0
"""GL003 4.2、4.3 与不平衡单因子随机效应扩展。"""

import math
from typing import Any

import numpy as np
from scipy.stats import f as f_distribution

from ..config.catalog import ENUMS
from ..errors import InputError
from ..io.shape import insufficient_homogeneity_replicates, insufficient_units
from .decision import compare
from .models import HomogeneityResult


def _anova(data: Any) -> dict[str, Any]:
    """GL003 4.2；扩展方法（Searle 等，页码待核）：n₀=(N-Σnᵢ²/N)/(g-1)。"""
    try:
        groups = [np.asarray(row, dtype=float) for row in data]
    except (ValueError, TypeError):
        raise InputError("均匀性数据须为数值序列") from None
    if insufficient_units(len(groups)) or any(
        row.ndim != 1 or insufficient_homogeneity_replicates(len(row)) or not np.isfinite(row).all()
        for row in groups
    ):
        raise InputError("至少需要两个单元、每单元两次有限数值")
    g = len(groups)
    counts = [len(row) for row in groups]
    total = sum(counts)
    n0 = (total - sum(n * n for n in counts) / total) / (g - 1)
    with np.errstate(over="ignore", invalid="ignore"):
        means = [float(row.mean()) for row in groups]
        grand = float(sum(n * mean for n, mean in zip(counts, means, strict=True)) / total)
        ssb = float(np.sum(np.asarray(counts) * (np.asarray(means) - grand) ** 2))
        ssw = float(sum(np.sum((row - mean) ** 2) for row, mean in zip(groups, means, strict=True)))
    db, dw = g - 1, total - g
    msb, msw = ssb / db, ssw / dw
    raw = (msb - msw) / n0
    if not all(math.isfinite(v) for v in (grand, ssb, ssw, msb, msw, raw)):
        raise InputError("数据范围导致数值溢出")
    return {
        "g": g,
        "m": counts[0] if len(set(counts)) == 1 else None,
        "counts": counts,
        "n0": n0,
        "means": means,
        "mean": grand,
        "SS_between": ssb,
        "SS_within": ssw,
        "df_between": db,
        "df_within": dw,
        "MS_between": msb,
        "MS_within": msw,
        "variance_raw": raw,
    }


def analyze_single(data: Any, sigma: float | None = None) -> dict[str, Any]:
    """B.1.2：不可重复测量时，用单测样本标准差保守估计不均匀性。"""
    try:
        groups = [np.asarray(row, dtype=float) for row in data]
    except (ValueError, TypeError):
        raise InputError("均匀性数据须为数值序列") from None
    if insufficient_units(len(groups)) or any(
        row.ndim != 1 or len(row) != 1 or not np.isfinite(row).all() for row in groups
    ):
        raise InputError("单测设计至少需要两个单元且每单元恰好一次有限测量")
    if sigma is not None and (not math.isfinite(sigma) or sigma <= 0):
        raise InputError("sigma 必须为正有限数")
    with np.errstate(over="ignore", invalid="ignore"):
        values = np.asarray([row[0] for row in groups])
        mean, sx = float(values.mean()), float(values.std(ddof=1))
    if not math.isfinite(mean) or not math.isfinite(sx):
        raise InputError("数据范围导致数值溢出")
    threshold = 0.3 * sigma if sigma is not None else None
    passed = compare(sx, threshold) <= 0 if threshold is not None else None
    return {
        "method": "single",
        "status": "OK",
        "design_status": "DESIGN_WARNING",
        "design_warnings": ["GB/T 28043-2019 B.1.2：选用重复性标准差足够低的测量方法"],
        "warnings": ["单测标准差含测量误差，以其代替样品间标准差的结论偏保守"],
        "g": len(groups),
        "m": 1,
        "counts": [1] * len(groups),
        "n0": None,
        "means": values.tolist(),
        "mean": mean,
        "SS_between": None,
        "SS_within": None,
        "df_between": len(groups) - 1,
        "df_within": 0,
        "MS_between": None,
        "MS_within": None,
        "F": None,
        "F_critical": None,
        "p": None,
        "variance_raw": None,
        "Ss": sx,
        "sigma": sigma,
        "threshold": threshold,
        "F_pass": None,
        "Ss_pass": passed,
        "Ss_status": "OK" if sigma is not None else "NOT_EVALUATED",
        "strict": False,
        "conclusion": passed,
        "sigma_source": None,
        "sigma_stage": None,
    }


def analyze(
    data: Any,
    sigma: float | None = None,
    alpha: float = 0.05,
    strict: bool = False,
    sigma_source: str | None = None,
    sigma_stage: str | None = None,
) -> HomogeneityResult:
    """按 GL003 4.2、4.3 计算 F=MS组间/MS组内 和 Ss。"""
    if not 0 < alpha < 1:
        raise InputError("alpha 必须在 0 和 1 之间")
    if sigma is not None and (not math.isfinite(sigma) or sigma <= 0):
        raise InputError("sigma 必须为正有限数")
    if sigma_stage is not None and sigma_stage not in ENUMS["sigma_stage"]:
        raise InputError("sigma 阶段应为 temporary 或 final")
    if sigma_source is not None and not isinstance(sigma_source, str):
        raise InputError("sigma 来源必须为文字")
    values = _anova(data)
    raw, msb, msw = values["variance_raw"], values["MS_between"], values["MS_within"]
    db, dw = values["df_between"], values["df_within"]
    ss = math.sqrt(max(0, raw))
    critical = float(f_distribution.ppf(1 - alpha, db, dw))
    stat = msb / msw if msw else None
    if stat is not None and not math.isfinite(stat):
        stat = None
    fpass = compare(stat, critical) < 0 if stat is not None else None
    threshold = 0.3 * sigma if sigma is not None else None
    sspass = compare(ss, threshold) <= 0 if threshold is not None else None
    conclusion = (
        (fpass and sspass if sspass is not None else (False if fpass is False else None))
        if strict
        else fpass
    )
    warnings = (["组间方差估计为负，Ss截零；不代表绝对均匀"] if raw < 0 else []) + (
        ["组内方差为零，F不可判定，请检查分辨力"] if stat is None else []
    )
    design_warnings = ["GL003 4.1 样品数不足10"] if values["g"] < 10 else []
    if len(set(values["counts"])) > 1:
        design_warnings.append("扩展方法：不平衡随机效应 ANOVA，采用有效重复数 n₀；需审核")
    return HomogeneityResult(
        **values,
        status="INDETERMINATE" if stat is None else "OK",
        design_status="DESIGN_WARNING" if design_warnings else "OK",
        design_warnings=design_warnings,
        warnings=warnings,
        F=stat,
        F_critical=critical,
        p=float(f_distribution.sf(stat, db, dw)) if stat is not None else None,
        Ss=ss,
        sigma=sigma,
        sigma_source=sigma_source,
        sigma_stage=sigma_stage if sigma is not None else None,
        threshold=threshold,
        F_pass=fpass,
        Ss_pass=sspass,
        Ss_status=(
            "NOT_EVALUATED"
            if sigma is None
            else "PROVISIONAL"
            if sigma_stage == "temporary"
            else "OK"
        ),
        strict=strict,
        conclusion=conclusion,
    )
