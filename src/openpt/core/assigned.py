# SPDX-License-Identifier: Apache-2.0
"""指定值及独立不确定度分量；GL002 4.3.1、4.3.2。"""

import math
from dataclasses import dataclass
from typing import Any

from ..errors import InputError
from .models import ResultMapping
from .robust import algorithm_a, median_niqr

# 扩展方法：参加者公议值的标准不确定度系数；ISO 13528 待核对条款号。
CONSENSUS_U_FACTOR = 1.25
METHODS = ("known", "certified", "reference", "expert_consensus", "participant_consensus")


@dataclass
class AssignedResult(ResultMapping):
    """指定值、标准不确定度、来源和分量映射。"""

    method: str
    value: float | None
    u: float | None
    source: str
    uncertainty_source: str
    consensus_method: str | None
    sigma_temporary: float | None
    sigma_final: float | None
    sigma_procedure: str
    sigma_prime: float | None
    u_hom: float
    u_stab: float
    hom_mapping: str
    stab_mapping: str
    status: str
    warnings: list[str]
    formula: str


def _number(value: Any, label: str, *, nonnegative: bool = False) -> float:
    """检查有限数和非负不确定度。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(f"{label}须为有限数值")
    number = float(value)
    if not math.isfinite(number) or (nonnegative and number < 0):
        raise InputError(f"{label}无效")
    return number


def assign_value(
    method: str,
    *,
    value: float | None = None,
    uncertainty: float | None = None,
    source: str = "",
    uncertainty_source: str = "",
    participants: Any = None,
    consensus_method: str = "robust_mean",
    sigma_temporary: float | None = None,
    sigma_final: float | None = None,
    sigma_procedure: str = "",
    u_hom: float = 0.0,
    u_stab: float = 0.0,
    hom_mapping: str = "none",
    stab_mapping: str = "none",
    hom_in_base: bool = False,
    stab_in_base: bool = False,
) -> AssignedResult:
    """GL002 4.3.1；扩展方法 u(x*)=1.25 s*/√p，ISO 13528 待核对条款号。

    外部定值和不确定度应由经批准的预算输入；分量按独立假定合成。
    """
    if method not in METHODS:
        raise InputError("未知指定值方法")
    if not isinstance(source, str) or not source.strip():
        raise InputError("指定值来源必填")
    if not isinstance(uncertainty_source, str) or not uncertainty_source.strip():
        raise InputError("指定值不确定度来源必填")
    if hom_mapping not in ("none", "assigned", "sigma_prime", "both") or stab_mapping not in (
        "none",
        "assigned",
        "sigma_prime",
        "both",
    ):
        raise InputError("分量映射无效")
    if not isinstance(hom_in_base, bool) or not isinstance(stab_in_base, bool):
        raise InputError("基础不确定度包含分量的标识必须为布尔值")
    uh = _number(u_hom, "u_hom", nonnegative=True)
    us = _number(u_stab, "u_stab", nonnegative=True)
    temporary = None if sigma_temporary is None else _number(sigma_temporary, "临时σ_pt")
    final = None if sigma_final is None else _number(sigma_final, "最终σ_pt")
    if any(x is not None and x <= 0 for x in (temporary, final)):
        raise InputError("σ_pt 必须为正")
    if (temporary is not None or final is not None) and not sigma_procedure.strip():
        raise InputError("须登记 σ_pt 确定程序")
    warnings: list[str] = []
    if method == "participant_consensus":
        if consensus_method == "robust_mean":
            robust = algorithm_a(participants)
            x, scale, count = robust.x, robust.s, robust.n
            if not robust.converged or robust.status != "OK":
                warnings.append("稳健统计未收敛或尺度为零，指定值不作评价")
        elif consensus_method == "median":
            robust_median = median_niqr(participants)
            x, scale, count = robust_median.median, robust_median.niqr, len(participants)
            if scale == 0:
                warnings.append("NIQR 为零，指定值不作评价")
        else:
            raise InputError("未知参加者公议方法")
        base_u = CONSENSUS_U_FACTOR * (scale / math.sqrt(count))
        formula = "扩展方法：u(X)=1.25·s*/√p；ISO 13528 待核对条款号"
    else:
        x = _number(value, "指定值")
        base_u = _number(uncertainty, "指定值标准不确定度", nonnegative=True)
        formula = "GL002 4.3.1、4.3.2：采用已评定并输入的标准不确定度"
    duplicate = hom_mapping == "both" or stab_mapping == "both"
    duplicate |= hom_in_base and hom_mapping in ("assigned", "sigma_prime")
    duplicate |= stab_in_base and stab_mapping in ("assigned", "sigma_prime")
    if duplicate:
        warnings.append("均匀性或稳定性分量重复计入，需审核并批准映射")
    if any(not math.isfinite(v) for v in (x, base_u)):
        raise InputError("指定值数值溢出")
    u = math.hypot(
        base_u, uh if hom_mapping == "assigned" else 0, us if stab_mapping == "assigned" else 0
    )
    selected_sigma = final if final is not None else temporary
    sigma_prime = (
        math.hypot(
            selected_sigma,
            uh if hom_mapping == "sigma_prime" else 0,
            us if stab_mapping == "sigma_prime" else 0,
        )
        if selected_sigma is not None
        else None
    )
    if not math.isfinite(u) or (sigma_prime is not None and not math.isfinite(sigma_prime)):
        raise InputError("不确定度合成溢出")
    return AssignedResult(
        method,
        x,
        u if not duplicate and not warnings else None,
        source,
        uncertainty_source,
        consensus_method if method == "participant_consensus" else None,
        temporary,
        final,
        sigma_procedure,
        sigma_prime,
        uh,
        us,
        hom_mapping,
        stab_mapping,
        "DESIGN_REVIEW" if duplicate else "NOT_EVALUATED" if warnings else "OK",
        warnings,
        formula,
    )
