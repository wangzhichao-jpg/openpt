# SPDX-License-Identifier: Apache-2.0
"""传递标准的逐点最大变差与独立样本 t 检验。"""

import math
from typing import Any

from ..errors import InputError
from .decision import compare
from .stability import analyze


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(f"{label}须为有限数")
    try:
        value = float(value)
    except OverflowError:
        raise InputError(f"{label}数值溢出") from None
    if not math.isfinite(value) or (positive and value <= 0):
        raise InputError(f"{label}须为{'正' if positive else ''}有限数")
    return value


def assess_point(
    observations: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    *,
    window: str = "all",
    summarized_delta: float | None = None,
) -> dict[str, Any]:
    """只计算明确指定的点与时间窗口，不把汇总变差伪造成测量序列。"""
    if window not in ("all", "transfer_only"):
        raise InputError("稳定性窗口应为 all 或 transfer_only")
    if not criteria:
        raise InputError("至少指定一个稳定性判据")
    values = []
    for row in observations:
        stage = row.get("stage")
        if stage not in ("传递前", "传递中", "传递后"):
            raise InputError("阶段应为传递前、传递中或传递后")
        value = _number(row.get("value"), "复测值")
        if window == "all" or stage in ("传递中", "传递后"):
            values.append(value)
    if summarized_delta is not None:
        if observations:
            raise InputError("汇总变差与测量序列不可同时输入")
        delta = _number(summarized_delta, "汇总变差")
        if delta < 0:
            raise InputError("汇总变差不能为负")
    else:
        if len(values) < 2:
            raise InputError("所选时间窗口至少需要两次测量")
        delta = max(values) - min(values)
    if not math.isfinite(delta):
        raise InputError("最大变差数值溢出")
    results = []
    for rule in criteria:
        kind = rule.get("kind")
        inclusive = rule.get("inclusive", False)
        if not isinstance(inclusive, bool):
            raise InputError("inclusive 须为布尔值")
        if kind in ("mpev", "u_ref"):
            amount = _number(rule.get("value"), "判据输入", positive=True)
            k = _number(rule.get("k"), "除数 k", positive=True)
            limit = amount / k
        elif kind == "fixed":
            limit = _number(rule.get("value"), "固定限值", positive=True)
        elif kind in ("one_sample", "two_sample"):
            if summarized_delta is not None:
                raise InputError("汇总变差不能用于 t 检验")
            if kind == "one_sample":
                result = analyze(
                    None,
                    [[v] for v in values],
                    method="one_sample",
                    reference=_number(rule.get("reference"), "参考值"),
                )
            else:
                before = rule.get("baseline")
                if not isinstance(before, list):
                    raise InputError("两样本检验须提供基线组")
                result = analyze(
                    [[_number(v, "基线值")] for v in before],
                    [[v] for v in values],
                    method="two_sample",
                )
            t, critical = result.t, result.critical
            passed = (
                None
                if t is None or critical is None
                else compare(abs(t), critical) <= 0
                if inclusive
                else compare(abs(t), critical) < 0
            )
            results.append(
                {
                    "kind": kind,
                    "value": t,
                    "limit": critical,
                    "inclusive": inclusive,
                    "pass": passed,
                    "detail": result.to_dict(),
                }
            )
            continue
        else:
            raise InputError("未知传递标准判据")
        passed = compare(delta, limit) <= 0 if inclusive else compare(delta, limit) < 0
        results.append(
            {"kind": kind, "value": delta, "limit": limit, "inclusive": inclusive, "pass": passed}
        )
    return {
        "window": window,
        "count": len(values) if summarized_delta is None else None,
        "delta_max": delta,
        "criteria": results,
        "conclusion": all(r["pass"] is True for r in results)
        if all(r["pass"] is not None for r in results)
        else None,
    }


def en_with_stability(
    difference: float,
    u_lab: float,
    u_ref: float,
    *,
    mechanism: str,
    delta: float | None = None,
    coverage_factor: float = 2.0,
    u_e: float | None = None,
    u_e_multiplier: float | None = None,
    ref_includes_stability: bool = False,
    ignore_condition: bool | None = None,
) -> dict[str, Any]:
    """A/B/C 互斥；不确定度来源无法排重时不输出 En。"""
    d = _number(difference, "差值")
    lab = _number(u_lab, "实验室扩展不确定度", positive=True)
    ref = _number(u_ref, "参考扩展不确定度", positive=True)
    k = _number(coverage_factor, "包含因子", positive=True)
    if not isinstance(ref_includes_stability, bool):
        raise InputError("参考不确定度包含稳定性标记须为布尔值")
    if mechanism not in ("A", "B", "C"):
        raise InputError("稳定性衔接机制应为 A、B 或 C")
    if mechanism == "A":
        if ref_includes_stability or u_e is not None or u_e_multiplier is not None:
            return {"status": "DESIGN_REVIEW", "En": None, "reason": "稳定性可能重复计入"}
        spread = _number(delta, "稳定性变差")
        if spread < 0:
            raise InputError("稳定性变差不能为负")
        u_stab = spread / (2 * math.sqrt(3))
        combined_ref = math.hypot(ref, k * u_stab)
        return {
            "status": "OK",
            "En": d / math.hypot(lab, combined_ref),
            "u_stab": u_stab,
            "U_ref": combined_ref,
            "U_E": None,
        }
    if mechanism == "B":
        if ref_includes_stability:
            return {
                "status": "DESIGN_REVIEW",
                "En": None,
                "reason": "参考不确定度已含稳定性，不能再外加 U_E",
            }
        if u_e is not None and u_e_multiplier is not None:
            raise InputError("U_E 不可同时指定固定值和倍率")
        if u_e_multiplier is not None:
            multiplier = _number(u_e_multiplier, "U_E 倍率")
            spread = _number(delta, "稳定性变差")
            if multiplier < 0 or spread < 0:
                raise InputError("U_E 倍率和稳定性变差不能为负")
            u_e = multiplier * spread
        extra = _number(u_e, "U_E")
        if extra < 0:
            raise InputError("U_E 不能为负")
        return {
            "status": "OK",
            "En": d / math.hypot(lab, ref, extra),
            "u_stab": None,
            "U_ref": ref,
            "U_E": extra,
        }
    if ignore_condition is not True or u_e is not None or u_e_multiplier is not None:
        return {
            "status": "DESIGN_REVIEW",
            "En": None,
            "reason": "忽略稳定性须有已核实的条件且不得再计入 U_E",
        }
    return {
        "status": "OK",
        "En": d / math.hypot(lab, ref),
        "u_stab": None,
        "U_ref": ref,
        "U_E": None,
    }
