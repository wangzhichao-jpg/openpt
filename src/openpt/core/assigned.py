# SPDX-License-Identifier: Apache-2.0
"""指定值及独立不确定度分量；GL002 4.3.1、4.3.2。"""

import math
import statistics
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
    base_u: float
    known_components: list[float] | None
    expert_values: list[float] | None
    consensus_method: str | None
    sigma_temporary: float | None
    sigma_final: float | None
    sigma_procedure: str
    sigma_prime: float | None
    u_hom: float
    u_stab: float
    hom_mapping: str
    stab_mapping: str
    hom_in_base: bool
    stab_in_base: bool
    status: str
    warnings: list[str]
    formula: str


def _number(value: Any, label: str, *, nonnegative: bool = False) -> float:
    """检查有限数和非负不确定度。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(f"{label}须为有限数值")
    try:
        number = float(value)
    except OverflowError:
        raise InputError(f"{label}数值溢出") from None
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
    expert_values: Any = None,
    known_components: Any = None,
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
    if known_components is not None and method != "known":
        raise InputError("制备分量仅适用于已知值方法")
    if expert_values is not None and method != "expert_consensus":
        raise InputError("专家结果仅适用于专家公议方法")
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
    components: list[float] | None = None
    expert: list[float] | None = None
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
    elif method == "known" and known_components is not None:
        if uncertainty is not None:
            raise InputError("已知值不可同时输入基础不确定度和制备分量")
        if not isinstance(known_components, (list, tuple)) or not known_components:
            raise InputError("制备分量须为非空列表")
        components = [
            _number(item, "制备标准不确定度分量", nonnegative=True) for item in known_components
        ]
        x = _number(value, "指定值")
        base_u = math.hypot(*components)
        formula = "扩展方法（独立分量合成）：u_base=√Σuᵢ²；GL002 4.3.1 a、4.3.2"
    elif method == "expert_consensus" and expert_values is not None:
        if value is not None or uncertainty is not None:
            raise InputError("专家结果与预先评定的值或不确定度不可同时输入")
        if not isinstance(expert_values, (list, tuple)) or len(expert_values) < 2:
            raise InputError("专家公议至少需要两个专家结果")
        expert = [_number(item, "专家结果") for item in expert_values]
        try:
            x = statistics.mean(expert)
            base_u = statistics.stdev(expert) / math.sqrt(len(expert))
        except (OverflowError, ValueError):
            raise InputError("专家公议结果溢出") from None
        formula = "扩展方法（独立同精度专家）：X=均值，u_base=s/√n；GL002 4.3.1 d"
    else:
        x = _number(value, "指定值")
        base_u = _number(uncertainty, "指定值标准不确定度", nonnegative=True)
        descriptions = {
            "known": "已知值：使用制备模型中已评定并输入的 u(X)",
            "certified": "有证参考值：使用证书或已评定并输入的 u(X)",
            "reference": "参考值：使用比对或并行测量已评定并输入的 u(X)",
            "expert_consensus": "专家公议值：使用已评定并输入的公议值 u(X)",
        }
        formula = "GL002 4.3.1、4.3.2：" + descriptions[method] + "；u_base=u_input"
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
        base_u,
        components,
        expert,
        consensus_method if method == "participant_consensus" else None,
        temporary,
        final,
        sigma_procedure,
        sigma_prime,
        uh,
        us,
        hom_mapping,
        stab_mapping,
        hom_in_base,
        stab_in_base,
        "DESIGN_REVIEW" if duplicate else "NOT_EVALUATED" if warnings else "OK",
        warnings,
        formula,
    )
