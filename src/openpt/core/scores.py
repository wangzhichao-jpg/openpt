# SPDX-License-Identifier: Apache-2.0
"""GL002 4.4.1.3、4.5.1 的定量能力统计量。"""

import math
from dataclasses import dataclass, field

from ..errors import InputError
from .decision import compare
from .models import ResultMapping


@dataclass
class ScoreResult(ResultMapping):
    """能力统计量、前提状态和与评价相分离的提示。"""

    statistic: str
    value: float | None
    status: str
    classification: str | None
    reason: str | None
    formula: str
    warnings: list[str] = field(default_factory=list)


def performance_score(
    statistic: str,
    x: float,
    assigned: float,
    *,
    sigma: float | None = None,
    sigma_pt_reference: float | None = None,
    delta_e: float | None = None,
    criterion_basis: str = "sigma_pt",
    u_assigned: float | None = None,
    u_participant: float | None = None,
    U_assigned: float | None = None,
    U_participant: float | None = None,
    k_assigned: float | None = None,
    k_participant: float | None = None,
    independent: bool | None = None,
    assigned_from_participants: bool = False,
    satisfactory: float = 2.0,
    unsatisfactory: float = 3.0,
    en_limit: float = 1.0,
) -> ScoreResult:
    """GL002 4.4.1.3 式(1)至(6)，GL002 4.5.1.1 的评价边界。"""
    formulas = {
        "D": "GL002 4.4.1.3 式(1)：D=x-X",
        "D%": "GL002 4.4.1.3 式(2)：D%=100(x-X)/X",
        "z": "GL002 4.4.1.3 式(3)：z=(x-X)/σ_pt",
        "zprime": "GL002 4.4.1.3 式(4)：z′=(x-X)/√(σ_pt²+u(X)²)",
        "zeta": "GL002 4.4.1.3 式(5)：ζ=(x-X)/√(u(x)²+u(X)²)",
        "En": "GL002 4.4.1.3 式(6)：En=(x-X)/√(U(x)²+U(X)²)",
    }
    if statistic not in formulas:
        raise InputError("未知能力统计量")
    for name, number in (
        ("x", x),
        ("X", assigned),
        ("满意阈值", satisfactory),
        ("不满意阈值", unsatisfactory),
        ("En 阈值", en_limit),
    ):
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(number)
        ):
            raise InputError(f"{name}必须是有限数值")
    if not 0 <= satisfactory < unsatisfactory or en_limit <= 0:
        raise InputError("评价阈值无效")
    for name, optional_number in (
        ("σ_pt", sigma),
        ("原始σ_pt", sigma_pt_reference),
        ("δ_E", delta_e),
        ("u(X)", u_assigned),
        ("u(x)", u_participant),
        ("U(X)", U_assigned),
        ("U(x)", U_participant),
        ("k(X)", k_assigned),
        ("k(x)", k_participant),
    ):
        if optional_number is not None and (
            isinstance(optional_number, bool)
            or not isinstance(optional_number, (int, float))
            or not math.isfinite(optional_number)
            or optional_number < 0
        ):
            raise InputError(f"{name}必须为非负有限数")
    if (independent is not None and not isinstance(independent, bool)) or not isinstance(
        assigned_from_participants, bool
    ):
        raise InputError("相关性配置无效")
    if criterion_basis not in ("sigma_pt", "delta_e"):
        raise InputError("指定值不确定度的判据依据无效")
    if criterion_basis == "delta_e" and (delta_e is None or delta_e <= 0):
        raise InputError("δ_E 判据须提供正的 delta_e")
    formula = formulas[statistic]
    warnings = []
    reference_sigma = sigma_pt_reference if sigma_pt_reference is not None else sigma
    threshold = (
        0.1 * delta_e
        if criterion_basis == "delta_e" and delta_e is not None
        else 0.3 * reference_sigma
        if reference_sigma is not None and reference_sigma > 0
        else None
    )
    if threshold == 0:
        raise InputError("指定值不确定度判据限值数值下溢")
    if threshold is not None and u_assigned is not None and compare(u_assigned, threshold) >= 0:
        condition = "u(X)≥0.1δ_E" if criterion_basis == "delta_e" else "u(X)≥0.3σ_pt"
        warnings.append(
            condition + "；可考虑 z′，依据 GB/T 28043-2019 9.2.1 式(10)、9.2.2；适用性须审查"
        )

    def absent(reason: str, status: str = "NOT_EVALUATED") -> ScoreResult:
        return ScoreResult(statistic, None, status, None, reason, formula, warnings)

    if statistic in ("z", "zprime") and (sigma is None or sigma <= 0):
        return absent("需要正的能力评定标准差 σ_pt")
    if statistic == "zprime" and u_assigned is None:
        return absent("z′ 需要指定值标准不确定度 u(X)")
    if statistic == "zprime" and assigned_from_participants:
        return absent("GL002 4.4.1.3 d 注1：参加者公议定值须审核相关性", "DESIGN_REVIEW")
    if statistic == "zeta" and (u_assigned is None or u_participant is None):
        return absent("ζ 需要 u(X) 和参加者 u(x)")
    if statistic == "En" and (
        U_assigned is None or U_participant is None or k_assigned is None or k_participant is None
    ):
        return absent("En 需要双方扩展不确定度 U 及包含因子 k")
    if statistic in ("zeta", "En") and assigned_from_participants:
        return absent("参加者结果参与定值，相关性需经批准模型处理", "DESIGN_REVIEW")
    if statistic in ("zeta", "En") and independent is not True:
        return absent(
            "须确认参加者结果与指定值不相关",
            "DESIGN_REVIEW" if independent is False else "NOT_EVALUATED",
        )
    if statistic == "En" and (k_assigned != 2 or k_participant != 2):
        return absent("GL002 4.4.1.3 f 使用 k=2，其他包含因子需批准模型", "DESIGN_REVIEW")
    diff = x - assigned
    if not math.isfinite(diff):
        raise InputError("差值溢出")
    if statistic == "D":
        score = diff
    elif statistic == "D%":
        if assigned == 0:
            return absent("指定值为零，百分相对差不可计算")
        score = (diff / assigned) * 100
    else:
        if statistic == "z":
            denominator = sigma
        elif statistic == "zprime":
            denominator = math.hypot(sigma or 0, u_assigned or 0)
        elif statistic == "zeta":
            denominator = math.hypot(u_assigned or 0, u_participant or 0)
        else:
            denominator = math.hypot(U_assigned or 0, U_participant or 0)
        if denominator is None or denominator == 0:
            return absent("分母为零")
        score = diff / denominator
    if not math.isfinite(score):
        raise InputError("能力统计量溢出")
    if statistic in ("D", "D%"):
        return ScoreResult(statistic, score, "OK", None, "差值未配置评价准则", formula, warnings)
    if statistic == "En":
        classification = "满意" if compare(abs(score), en_limit) <= 0 else "不满意"
    else:
        classification = (
            "满意"
            if compare(abs(score), satisfactory) <= 0
            else "可疑"
            if compare(abs(score), unsatisfactory) < 0
            else "不满意"
        )
    return ScoreResult(statistic, score, "OK", classification, None, formula, warnings)
