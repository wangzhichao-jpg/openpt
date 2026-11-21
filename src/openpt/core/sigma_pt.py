# SPDX-License-Identifier: Apache-2.0
"""能力评定标准差的显式来源与一次修约。"""

import math
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any

import numpy as np

from ..errors import InputError
from .robust import MAD_FACTOR, algorithm_a, algorithm_s, median_niqr

QUANTILE_LABELS = {
    "linear": "linear，type 7，Excel QUARTILE.INC/PERCENTILE.INC",
    "weibull": "weibull，type 6，Excel QUARTILE.EXC/PERCENTILE.EXC",
    "hazen": "hazen，type 5",
    "median_unbiased": "median_unbiased，type 8",
}
METHOD_LABELS = {
    "niqr": "参加者 NIQR",
    "made": "参加者 MADe",
    "algorithm_a": "参加者算法 A 稳健标准差",
    "algorithm_s": "算法 S 稳健联合标准差",
}


def round_significant(value: float, digits: int) -> float:
    """GB/T 8170 一次修约：十进制五成双，不连续修约。"""
    if (
        not math.isfinite(value)
        or isinstance(digits, bool)
        or not isinstance(digits, int)
        or digits < 1
    ):
        raise ValueError("须为有限数及正整数有效位数")
    number = Decimal(str(value))
    if not number:
        return 0.0
    if digits >= len(number.as_tuple().digits):
        return value
    quantum = Decimal(1).scaleb(number.adjusted() - digits + 1)
    with localcontext() as context:
        context.prec = max(34, digits + 10)
        return float(number.quantize(quantum, rounding=ROUND_HALF_EVEN))


def determine(data: dict[str, Any]) -> dict[str, Any] | None:
    """在判据计算之前确定 σ_pt；旧手工模式不生成新结果。"""
    cfg = data["config"]
    assigned = data.get("assigned_config", {})
    method = assigned.get("sigma_pt_method") or "manual"
    if method == "manual":
        return None
    participants = [p["value"] for p in data.get("participants", [])]
    digits = assigned.get("sigma_pt_sig_digits")
    info: dict[str, Any] = {"method": method, "label": METHOD_LABELS[method]}
    if method == "algorithm_s":
        values = data.get("algorithm_s_values", [])
        if len(values) < 2 or data.get("algorithm_s_df") is None:
            raise InputError("算法 S 需要至少两个标准差和自由度", sheet="算法S")
        s = algorithm_s(
            values,
            data["algorithm_s_df"],
            max_iterations=int(cfg.get("algorithm_s_max_iterations") or 1000),
            stop_rule=cfg.get("algorithm_s_stop_rule") or "gl002",
            tolerance=float(cfg.get("algorithm_s_tolerance") or 1e-12),
        )
        if not s.converged:
            raise InputError("算法 S 未收敛，不能用作 σ_pt", sheet="算法S")
        info.update(p=len(values), w=s.w, algorithm_s=s.to_dict())
        raw = s.w
    else:
        if len(participants) < 2:
            raise InputError("由参加者结果确定 σ_pt 须至少提供两个结果", sheet="参加者结果")
        arr = np.asarray(participants, dtype=float)
        median = float(np.median(arr))
        info.update(p=len(participants), median=median)
        if method == "niqr":
            quantile = cfg.get("quantile_method") or "linear"
            if quantile == "weibull" and len(participants) < 3:
                raise InputError("weibull 四分位数至少需要三个结果", sheet="参加者结果")
            niqr = median_niqr(participants, quantile)
            info.update(
                quantile_method=quantile,
                quantile_label=QUANTILE_LABELS[quantile],
                q1=niqr.q1,
                q3=niqr.q3,
                iqr=niqr.iqr,
            )
            raw = niqr.niqr
        elif method == "made":
            mad = float(np.median(np.abs(arr - median)))
            info["mad"] = mad
            raw = MAD_FACTOR * mad
        else:
            a = algorithm_a(
                participants,
                rule=cfg.get("algorithm_a_rule") or "gl002",
                simplified=cfg.get("algorithm_a_simplified") or False,
                tolerance=float(cfg.get("algorithm_a_tolerance") or 1e-10),
                max_iterations=int(cfg.get("algorithm_a_max_iterations") or 1000),
            )
            if not a.converged or a.status != "OK":
                raise InputError("算法 A 未收敛或稳健尺度为零，不能用作 σ_pt", sheet="参加者结果")
            raw = a.s
            info.update(s=raw, algorithm_a_rule=a.rule)
    if not math.isfinite(raw) or raw <= 0:
        raise InputError(
            "计算得到的 σ_pt 必须为正有限数", sheet="指定值与不确定度", field="sigma_pt_method"
        )
    rounded = round_significant(raw, int(digits)) if digits not in (None, "") else raw
    if not math.isfinite(rounded) or rounded <= 0:
        raise InputError(
            "修约后 σ_pt 必须为正有限数", sheet="指定值与不确定度", field="sigma_pt_sig_digits"
        )
    info.update(
        raw=raw, value=rounded, sig_digits=int(digits) if digits not in (None, "") else None
    )
    return info
