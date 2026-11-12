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
    selected_rows = []
    for row in observations:
        stage = row.get("stage")
        if stage not in ("传递前", "传递中", "传递后"):
            raise InputError("阶段应为传递前、传递中或传递后")
        value = _number(row.get("value"), "复测值")
        if window == "all" or stage in ("传递中", "传递后"):
            values.append(value)
            selected_rows.append(row)
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
                comparison = values
                if rule.get("group2"):
                    comparison = [
                        _number(row["value"], "比较组值")
                        for row in selected_rows
                        if row.get("group") == rule["group2"]
                    ]
                result = analyze(
                    [[_number(v, "基线值")] for v in before],
                    [[v] for v in comparison],
                    method="two_sample",
                )
            t, critical = result.t, result.critical
            if rule.get("critical_override") is not None:
                critical = _number(rule["critical_override"], "报告临界值", positive=True)
                if (
                    not isinstance(rule.get("critical_source"), str)
                    or not rule["critical_source"].strip()
                ):
                    raise InputError("采用报告临界值时须登记来源")
            passed = (
                None
                if t is None or critical is None
                else compare(abs(t), critical) <= 0
                if inclusive
                else compare(abs(t), critical) < 0
            )
            detail = result.to_dict()
            if rule.get("critical_override") is not None:
                detail["theoretical_critical"] = detail["critical"]
                detail["critical"] = critical
                detail["pass"] = passed
            results.append(
                {
                    "kind": kind,
                    "value": t,
                    "limit": critical,
                    "critical_source": rule.get("critical_source")
                    if rule.get("critical_override") is not None
                    else "GL003 两侧 t 分位数",
                    "inclusive": inclusive,
                    "pass": passed,
                    "detail": detail,
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
        "conclusion": False
        if any(r["pass"] is False for r in results)
        else True
        if all(r["pass"] is True for r in results)
        else None,
    }


def assess_transfer(
    records: list[dict[str, Any]], configs: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """按标准器与校准点分组，禁止未登记的测量或单位混用。"""
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in configs}
    for row in records:
        key = f"{row['standard']}|{row['point']}"
        if key not in configs:
            raise InputError(f"传递标准 {key} 未登记逐点配置")
        if row.get("unit") != configs[key].get("unit"):
            raise InputError(f"传递标准 {key} 的测量单位与配置不一致")
        grouped[key].append(row)
    results = {}
    for key, cfg in configs.items():
        rules = []
        for rule in cfg["criteria"]:
            current = dict(rule)
            if (
                current.get("kind") == "two_sample"
                and "baseline" in current
                and current.get("group1")
            ):
                raise InputError("两样本基线不能同时以测量组和列表指定")
            if current.get("kind") == "two_sample" and "baseline" not in current:
                if current.get("group1") or current.get("group2"):
                    if (
                        not all(
                            isinstance(current.get(name), str) and current[name]
                            for name in ("group1", "group2")
                        )
                        or current["group1"] == current["group2"]
                    ):
                        raise InputError("两样本检验须指定两个不同测量组")
                    current["baseline"] = [
                        row["value"]
                        for row in grouped[key]
                        if row.get("group") == current["group1"]
                    ]
                else:
                    if cfg["window"] != "transfer_only":
                        raise InputError("自动选取基线时两样本检验须选择传递期间窗口")
                    current["baseline"] = [
                        row["value"] for row in grouped[key] if row["stage"] == "传递前"
                    ]
            rules.append(current)
        result = assess_point(
            grouped[key], rules, window=cfg["window"], summarized_delta=cfg.get("summarized_delta")
        )
        result.update(
            {
                "standard": cfg["standard"],
                "point": cfg["point"],
                "unit": cfg["unit"],
                "source": cfg["source"],
                "uncertainty": dict(cfg.get("uncertainty") or {}),
            }
        )
        options = result["uncertainty"]
        allowed = {
            "mechanism",
            "source",
            "delta",
            "U_E",
            "multiplier",
            "ref_includes_stability",
            "ignore_condition",
            "condition_source",
            "effect",
            "measurement_uncertainty",
        }
        if set(options) - allowed:
            raise InputError(f"传递标准 {key} 的不确定度配置包含未知字段")
        for field in ("ref_includes_stability", "ignore_condition"):
            if options.get(field) is not None and not isinstance(options[field], bool):
                raise InputError(f"{field} 须为布尔值")
        mechanism = options.get("mechanism")
        if mechanism not in (None, "", "A", "B", "C"):
            raise InputError(f"传递标准 {key} 的不确定度机制无效")
        if mechanism:
            if not isinstance(options.get("source"), str) or not options["source"].strip():
                raise InputError(f"传递标准 {key} 的不确定度机制须登记来源")
            spread = _number(options.get("delta", result["delta_max"]), "稳定性变差")
            if spread < 0:
                raise InputError("稳定性变差不能为负")
            if mechanism == "A":
                result["u_stab"] = spread / (2 * math.sqrt(3))
                if (
                    options.get("U_E") is not None
                    or options.get("multiplier") is not None
                    or options.get("ref_includes_stability") is True
                ):
                    result["uncertainty_status"] = "DESIGN_REVIEW"
                else:
                    result["uncertainty_status"] = "OK"
            elif mechanism == "B":
                if options.get("U_E") is not None and options.get("multiplier") is not None:
                    raise InputError("U_E 不可同时指定固定值和倍率")
                extra = options.get("U_E")
                if options.get("multiplier") is not None:
                    extra = _number(options["multiplier"], "U_E 倍率") * spread
                result["U_E"] = _number(extra, "U_E")
                if result["U_E"] < 0:
                    raise InputError("U_E 不能为负")
                result["uncertainty_status"] = (
                    "DESIGN_REVIEW" if options.get("ref_includes_stability") is True else "OK"
                )
            else:
                valid = (
                    options.get("ignore_condition") is True
                    and isinstance(options.get("condition_source"), str)
                    and bool(options["condition_source"].strip())
                    and options.get("U_E") is None
                    and options.get("multiplier") is None
                    and options.get("ref_includes_stability") is not True
                )
                if ("effect" in options) != ("measurement_uncertainty" in options):
                    raise InputError("忽略条件数值须同时登记影响量和测量结果不确定度")
                if "effect" in options:
                    effect = _number(options["effect"], "不稳定性影响量")
                    bound = (
                        _number(
                            options["measurement_uncertainty"], "测量结果不确定度", positive=True
                        )
                        / 3
                    )
                    if effect < 0:
                        raise InputError("不稳定性影响量不能为负")
                    valid = valid and compare(effect, bound) < 0
                result["uncertainty_status"] = "OK" if valid else "DESIGN_REVIEW"
        else:
            result["uncertainty_status"] = "NOT_EVALUATED"
        results[key] = result
    return results


def summarize_transfer(points: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """先按标准器汇总各校准点，再给出总体三态结论。"""
    groups: dict[str, dict[str, Any]] = {}
    for point in points.values():
        standard = str(point["standard"])
        groups.setdefault(standard, {})[str(point["point"])] = point["conclusion"]

    def conclude(values: list[Any]) -> bool | None:
        if any(value is False for value in values):
            return False
        return True if values and all(value is True for value in values) else None

    grouped = {
        key: {"points": values, "conclusion": conclude(list(values.values()))}
        for key, values in groups.items()
    }
    return {
        "standards": grouped,
        "conclusion": conclude([entry["conclusion"] for entry in grouped.values()]),
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
