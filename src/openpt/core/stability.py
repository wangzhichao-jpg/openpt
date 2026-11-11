# SPDX-License-Identifier: Apache-2.0
"""GL003 5.2/5.3；重复值模型仅供复核。"""

import math
from typing import Any

import numpy as np
from scipy.stats import t as t_distribution

from ..errors import InputError
from .models import StabilityResult


def _observations(data: Any, pooled_repeats: bool) -> Any:
    try:
        a = np.asarray(data, dtype=float)
    except (ValueError, TypeError):
        raise InputError("稳定性数据须为数值矩阵") from None
    if a.ndim != 2 or a.shape[0] < 2 or a.shape[1] < 1 or not np.isfinite(a).all():
        raise InputError("稳定性至少需要两个单元及有限数值")
    with np.errstate(over="ignore", invalid="ignore"):
        observations = a.ravel() if pooled_repeats else a.mean(axis=1)
    if not np.isfinite(observations).all():
        raise InputError("稳定性观测均值数值溢出")
    return observations


def summary_t(
    mean1: float,
    mean2: float,
    s1: float,
    s2: float,
    n1: int,
    n2: int,
    alpha: float = 0.05,
    welch: bool = False,
) -> StabilityResult:
    """按 GL003 5.2.2 计算 pooled t，或按 Welch 模型复核。"""
    if (
        n1 < 2
        or n2 < 2
        or min(s1, s2) < 0
        or not all(math.isfinite(x) for x in (mean1, mean2, s1, s2, alpha))
        or not 0 < alpha < 1
    ):
        raise InputError("t 检验参数无效")
    a, b = s1 * s1 / n1, s2 * s2 / n2
    if not math.isfinite(a) or not math.isfinite(b):
        raise InputError("稳定性方差数值溢出")
    if welch:
        total = a + b
        if not math.isfinite(total):
            raise InputError("稳定性标准误数值溢出")
        se = math.sqrt(total)
        denom = (a / total) ** 2 / (n1 - 1) + (b / total) ** 2 / (n2 - 1) if total else 0
        df = 1 / denom if denom else None
    else:
        df = n1 + n2 - 2
        pooled = (n1 - 1) / df * (s1 * s1) + (n2 - 1) / df * (s2 * s2)
        se = math.sqrt(pooled * (1 / n1 + 1 / n2))
    difference = abs(mean1 - mean2)
    if not math.isfinite(difference) or not math.isfinite(se):
        raise InputError("稳定性均值差或标准误数值溢出")
    t = difference / se if se else None
    if t is not None and not math.isfinite(t):
        t = None
    critical = float(t_distribution.ppf(1 - alpha / 2, df)) if df else None
    return StabilityResult(
        t=t,
        df=df,
        p=float(2 * t_distribution.sf(t, df)) if t is not None and df else None,
        critical=critical,
        passed=t < critical if t is not None and critical else None,
        difference=difference,
        se=se,
        s1=s1,
        s2=s2,
        mean1=mean1,
        mean2=mean2,
        n1=n1,
        n2=n2,
        status="OK" if t is not None else "INDETERMINATE",
    )


def _one_sample(y: Any, reference: float | None, alpha: float) -> dict[str, Any]:
    """按 GL003 5.2.1 计算均值与参考值的 t 检验。"""
    if reference is None or not math.isfinite(reference):
        raise InputError("单样本检验需要参考值")
    n = len(y)
    with np.errstate(over="ignore", invalid="ignore"):
        mean, sd = float(y.mean()), float(y.std(ddof=1))
    se = sd / math.sqrt(n)
    diff = abs(mean - reference)
    if not all(math.isfinite(v) for v in (mean, sd, se, diff)):
        raise InputError("稳定性统计量数值溢出")
    t = diff / se if se else None
    if t is not None and not math.isfinite(t):
        raise InputError("稳定性 t 值数值溢出")
    df = n - 1
    crit = float(t_distribution.ppf(1 - alpha / 2, df))
    return StabilityResult(
        t=t,
        df=df,
        p=float(2 * t_distribution.sf(t, df)) if t is not None else None,
        critical=crit,
        passed=t < crit if t is not None else None,
        difference=diff,
        se=se,
        s1=sd,
        mean1=mean,
        reference=reference,
        n1=n,
        status="OK" if t is not None else "INDETERMINATE",
    ).to_dict()


def _two_sample(baseline: Any, y: Any, alpha: float, model: str) -> dict[str, Any]:
    """按 GL003 5.2.2 或复核模型计算两均值 t。"""
    x = _observations(baseline, model != "unit_pooled")
    with np.errstate(over="ignore", invalid="ignore"):
        mean_x, mean_y = float(x.mean()), float(y.mean())
        sd_x, sd_y = float(x.std(ddof=1)), float(y.std(ddof=1))
    return summary_t(
        mean_x, mean_y, sd_x, sd_y, len(x), len(y), alpha, model == "repeats_welch"
    ).to_dict()


def analyze(
    baseline: Any,
    followup: Any,
    sigma: float | None = None,
    alpha: float = 0.05,
    method: str = "two_sample",
    reference: float | None = None,
    model: str = "unit_pooled",
) -> StabilityResult:
    """按 GL003 5.2 计算 t 并按 5.3 对比均值差与 0.3σ。"""
    if model not in ("unit_pooled", "repeats_pooled", "repeats_welch"):
        raise InputError("未知稳定性模型")
    if method not in ("one_sample", "two_sample"):
        raise InputError("未知稳定性方法")
    if not 0 < alpha < 1:
        raise InputError("alpha 无效")
    if sigma is not None and (not math.isfinite(sigma) or sigma <= 0):
        raise InputError("sigma 无效")
    y = _observations(followup, model != "unit_pooled")
    result = (
        _one_sample(y, reference, alpha)
        if method == "one_sample"
        else _two_sample(baseline, y, alpha, model)
    )
    result.update(
        {
            "model": model,
            "method": method,
            "threshold": 0.3 * sigma if sigma is not None else None,
            "mean_difference_pass": result["difference"] <= 0.3 * sigma
            if sigma is not None
            else None,
            "mean_difference_status": "OK" if sigma is not None else "NOT_EVALUATED",
            "design_warnings": [],
        }
    )
    if len(followup) < 6 or (method == "two_sample" and len(baseline) < 6):
        result["design_status"] = "DESIGN_WARNING"
        result["design_warnings"].append("GL003 5.2 建议每组不少于6个观测单元")
    return StabilityResult.from_dict(result)
