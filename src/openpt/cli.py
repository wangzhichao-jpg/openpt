# SPDX-License-Identifier: Apache-2.0
"""命令行入口。"""

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from . import __version__
from .config.catalog import ENUMS
from .config.sigma import criterion_sigma
from .core.assigned import AssignedResult, assign_value
from .core.decision import compare
from .core.gbt28043 import criterion_limit as gbt_criterion_limit
from .core.gbt28043 import homogeneity as gbt_homogeneity
from .core.gbt28043 import period_options as gbt_period_options
from .core.gbt28043 import stability as gbt_stability
from .core.homogeneity import analyze as homogeneity
from .core.homogeneity import analyze_single as single_homogeneity
from .core.robust import algorithm_a, algorithm_s, median_niqr
from .core.scores import performance_score
from .core.stability import analyze as stability
from .core.transfer import assess_transfer, summarize_transfer
from .core.trend import configured_uncertainty, fit_series
from .core.zscore import zscore
from .errors import InputError
from .io.excel import template
from .io.shape import stability_structure_problem
from .report.docx import make_report


def _option(config: dict[str, Any], key: str, default: Any) -> Any:
    value = config.get(key)
    return default if value in (None, "") else value


def _participant_results(
    data: dict[str, Any], sigma: float | None, *, legacy_scores: bool = True
) -> dict[str, Any]:
    """计算 GL002 附录 A.2 算法 A 及 GL002 4.4 的 z。"""
    cfg = data["config"]
    simplified = _option(cfg, "algorithm_a_simplified", False)
    if not isinstance(simplified, bool):
        raise ValueError("algorithm_a_simplified 必须是布尔值")
    values = [p["value"] for p in data["participants"]]
    result: dict[str, Any] = {}
    if len(values) >= 2:
        result["算法A"] = algorithm_a(
            values,
            tolerance=float(_option(cfg, "algorithm_a_tolerance", 1e-10)),
            max_iterations=int(_option(cfg, "algorithm_a_max_iterations", 1000)),
            simplified=simplified,
            rule=str(_option(cfg, "algorithm_a_rule", "gl002")),
        ).to_dict()
        result["中位数NIQR"] = median_niqr(values).to_dict()
        # 绝对容差对照独立于选定停止规则，供附录和敏感性提示使用。
        result["算法A_收敛对照"] = algorithm_a(
            values, rule="absolute", tolerance=1e-12, max_iterations=10000
        ).to_dict()
    else:
        result["稳健统计状态"] = "NOT_EVALUATED：至少需要两个参加者结果"
    sigma_pt = float(cfg["sigma_pt"]) if cfg.get("sigma_pt") not in (None, "") else sigma
    if (
        legacy_scores
        and cfg.get("assigned") not in (None, "")
        and sigma_pt is not None
        and not data.get("assigned_config", {}).get("method")
    ):
        result["参加者z"] = {
            p["id"]: zscore(
                p["value"],
                float(cfg["assigned"]),
                sigma_pt,
                float(_option(cfg, "z_satisfactory", 2)),
                float(_option(cfg, "z_unsatisfactory", 3)),
            ).to_dict()
            for p in data["participants"]
        }
    return result


def _gbt_stability_disposition(
    assigned: AssignedResult, options: dict[str, Any], periods: dict[str, Any]
) -> dict[str, Any]:
    """连接稳定性证据及用户评定的预算；不从均值差生成不确定度。"""
    disposition = _option(options, "stability_disposition", "pending")
    reason = _option(options, "stability_disposition_reason", "")
    if disposition not in ENUMS["stability_disposition"]:
        raise InputError("stability_disposition 应为 pending、budgeted、reviewed 或 withhold")
    if not isinstance(reason, str):
        raise InputError("稳定性处置依据须为文字")
    flagged = {name: p for name, p in periods.items() if p.get("conclusion") is not True}
    if disposition in ("budgeted", "reviewed") and flagged and not reason.strip():
        raise InputError("稳定性处置须登记书面依据")
    if disposition == "budgeted" and flagged:
        storage_flagged = any(p.get("kind") != "transport" for p in flagged.values())
        transport_flagged = any(p.get("kind") == "transport" for p in flagged.values())
        stable_mapped = (
            assigned.u_stab > 0 and assigned.stab_mapping in ("assigned", "sigma_prime")
        ) or assigned.stab_in_base
        transport_mapped = (
            (assigned.u_trans > 0 and assigned.trans_mapping == "assigned")
            or assigned.trans_in_base
            or (assigned.trans_in_stab and stable_mapped)
        )
        if (storage_flagged and not stable_mapped) or (transport_flagged and not transport_mapped):
            raise InputError("稳定性或运输影响尚未登记到不确定度预算；不得凭均值差自动估算")
    if disposition == "withhold" or (flagged and disposition == "pending"):
        assigned.status = "DESIGN_REVIEW"
        assigned.u = None
        assigned.sigma_prime = None
        assigned.warnings.append("稳定性或运输处置未完成，或已登记暂停评价")
    elif flagged:
        assigned.warnings.append("稳定性处置依据由用户登记，软件不能验证审批、独立性或影响评定")
    return {
        "stability_disposition": disposition,
        "stability_disposition_reason": reason,
        "stability_flagged_periods": list(flagged),
    }


def _transfer_score_options(
    data: dict[str, Any],
    calculations: dict[str, Any],
    assigned: AssignedResult,
    participant_id: str,
) -> tuple[dict[str, Any], str | None, str]:
    """按参加者绑定逐点机制；缺少配置或重复计入时阻断 En。"""
    points = calculations.get("传递标准稳定性", {})
    if not points:
        return {}, None, ""
    raw = data["config"].get("transfer_en_map")
    if raw not in (None, ""):

        def unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
            output: dict[str, Any] = {}
            for item_key, value in items:
                if item_key in output:
                    raise InputError("transfer_en_map 含重复参加者编号")
                output[item_key] = value
            return output

        try:
            mapping = (
                json.loads(raw, object_pairs_hook=unique_pairs) if isinstance(raw, str) else raw
            )
        except ValueError:
            raise InputError("transfer_en_map 须为有效 JSON 对象") from None
        if not isinstance(mapping, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()
        ):
            raise InputError("transfer_en_map 须将参加者编号映射到标准器|校准点")
        key = mapping.get(participant_id)
    else:
        key = next(iter(points)) if len(points) == 1 else None
    if key not in points:
        return {}, "参加者未绑定唯一的传递标准校准点", ""
    point = points[key]
    options = point.get("uncertainty", {})
    if point.get("conclusion") is not True:
        return {}, "传递标准稳定性未通过或未评价，En 须先审核", str(key)
    if point.get("uncertainty_status") != "OK":
        return {}, "传递标准稳定性衔接条件未通过审核或未登记", str(key)
    source = f"传递标准 {key}；机制 {options.get('mechanism')}；来源 {options.get('source')}"
    already = bool(
        assigned.stab_in_base
        or (assigned.u_stab > 0 and assigned.stab_mapping in ("assigned", "both"))
    )
    if options.get("mechanism") == "A":
        if already:
            return {}, "稳定性已计入指定值不确定度，不得再次合成", source
        base = data.get("assigned_config", {}).get("U_assigned")
        if base is None:
            return {}, "机制 A 缺少参考值扩展不确定度", source
        if (
            isinstance(base, bool)
            or not isinstance(base, (int, float))
            or not math.isfinite(base)
            or base < 0
        ):
            raise InputError("参考值扩展不确定度须为非负有限数")
        return {"U_assigned": math.hypot(base, 2 * point["u_stab"])}, None, source
    if options.get("mechanism") == "B":
        return {"U_E": point["U_E"], "stability_in_U_ref": already}, None, source
    return {}, None, source


def _assigned_results(
    data: dict[str, Any],
    calculations: dict[str, Any],
    *,
    basis: str = "sigma_pt",
    delta_e: float | None = None,
) -> dict[str, Any]:
    """执行指定值建模和 GL002 4.4.1.3 选定统计量。"""
    a = data.get("assigned_config", {})
    keys = (
        "value",
        "uncertainty",
        "source",
        "uncertainty_source",
        "consensus_method",
        "sigma_temporary",
        "sigma_final",
        "sigma_procedure",
        "u_hom",
        "u_stab",
        "hom_mapping",
        "stab_mapping",
        "hom_in_base",
        "stab_in_base",
        "u_trans",
        "trans_mapping",
        "trans_in_base",
        "trans_in_stab",
    )
    options = {key: a[key] for key in keys if key in a}
    hom_source = a.get("hom_source") or "manual"
    if hom_source not in ENUMS["hom_source"]:
        raise InputError("hom_source 应为 manual 或 gbt_ss")
    if hom_source == "gbt_ss":
        if _option(data["config"], "criterion_standard", "gl003") != "gbt28043":
            raise InputError("从标准模式引用 ss 须选择 gbt28043")
        h = calculations.get("GB/T均匀性")
        if not h:
            raise InputError("引用 ss 须提供均匀性数据")
        if a.get("hom_mapping") not in ("assigned", "sigma_prime", "both"):
            raise InputError("引用 ss 须明确登记分量映射")
        if a.get("u_hom") not in (None, "", 0, 0.0):
            raise InputError("引用 ss 时不得同时手工输入 u_hom")
        options["u_hom"] = h["ss"]
    if (
        a.get("method") == "participant_consensus"
        and _option(a, "consensus_method", "robust_mean") == "robust_mean"
    ):
        cfg = data["config"]
        options.update(
            {
                "algorithm_a_rule": str(_option(cfg, "algorithm_a_rule", "gl002")),
                "algorithm_a_tolerance": float(_option(cfg, "algorithm_a_tolerance", 1e-10)),
                "algorithm_a_max_iterations": int(_option(cfg, "algorithm_a_max_iterations", 1000)),
                "algorithm_a_simplified": _option(cfg, "algorithm_a_simplified", False),
            }
        )
    for key in ("known_components", "expert_values"):
        if a.get(key) not in (None, ""):
            if not isinstance(a[key], str):
                raise InputError(f"{key} 须为逗号分隔的数值列表")
            try:
                options[key] = [float(item.strip()) for item in a[key].split(",")]
            except ValueError:
                raise InputError(f"{key} 须为逗号分隔的数值列表") from None
    assigned = assign_value(
        a["method"], participants=[p["value"] for p in data["participants"]], **options
    )
    disposition_details = {}
    if _option(data["config"], "criterion_standard", "gl003") == "gbt28043":
        disposition_details = _gbt_stability_disposition(
            assigned, a, calculations.get("GB/T稳定性", {})
        )
    assigned_details = assigned.to_dict()
    assigned_details.update(disposition_details)
    if (
        a.get("method") == "participant_consensus"
        and _option(a, "consensus_method", "robust_mean") == "robust_mean"
        and calculations.get("算法A", {}).get("rule") not in (None, "gl002")
    ):
        assigned_details["consensus_algorithm_rule"] = calculations["算法A"]["rule"]
    if hom_source == "gbt_ss":
        assigned_details["hom_source"] = (
            "GB/T 28043-2019 B.1.2 单测标准差"
            if calculations.get("GB/T均匀性", {}).get("m") == 1
            else "GB/T 28043-2019 B.3 ss"
        )
    assigned_details.update(
        {key: a.get(key) for key in ("U_assigned", "k_assigned", "independent")}
    )
    result: dict[str, Any] = {"指定值与不确定度": assigned_details}
    kind = _option(data["config"], "score_type", "z")
    if kind not in ENUMS["score_type"]:
        raise ValueError("未知统计量类型")
    kinds = ("D", "D%", "z", "zprime", "zeta", "En") if kind == "all" else (kind,)
    participant_scores: dict[str, Any] = {}
    for participant in data["participants"]:
        scores = {}
        for name in kinds:
            if assigned.status != "OK" or assigned.value is None:
                scores[name] = {
                    "statistic": name,
                    "value": None,
                    "status": assigned.status,
                    "classification": None,
                    "reason": "指定值或分量映射未通过审核",
                    "formula": "GL002 4.4.1.3",
                    "warnings": assigned.warnings,
                }
            else:
                extra, transfer_problem, transfer_source = (
                    _transfer_score_options(data, calculations, assigned, participant["id"])
                    if name == "En"
                    else ({}, None, "")
                )
                score_result = performance_score(
                    name,
                    participant["value"],
                    assigned.value,
                    sigma=assigned.sigma_prime,
                    sigma_pt_reference=assigned.sigma_final
                    if assigned.sigma_final is not None
                    else assigned.sigma_temporary,
                    u_assigned=assigned.u,
                    delta_e=delta_e,
                    criterion_basis=basis,
                    u_participant=participant.get("u"),
                    U_assigned=extra.get("U_assigned", a.get("U_assigned")),
                    U_E=extra.get("U_E"),
                    stability_in_U_ref=extra.get("stability_in_U_ref", False),
                    U_participant=participant.get("U"),
                    k_assigned=a.get("k_assigned"),
                    k_participant=participant.get("k"),
                    independent=a.get("independent"),
                    assigned_from_participants=assigned.method == "participant_consensus",
                    satisfactory=float(_option(data["config"], "z_satisfactory", 2)),
                    unsatisfactory=float(_option(data["config"], "z_unsatisfactory", 3)),
                    en_limit=float(_option(data["config"], "en_limit", 1)),
                )
                if transfer_problem:
                    score_result.status = "DESIGN_REVIEW"
                    score_result.value = None
                    score_result.classification = None
                    score_result.reason = transfer_problem
                if transfer_source:
                    score_result.warnings.append(transfer_source)
                if assigned.sigma_final is None and assigned.sigma_temporary is not None:
                    score_result.warnings.append("能力评定标准差为临时值，评价仅供暂时参考")
                scores[name] = score_result.to_dict()
        participant_scores[participant["id"]] = scores
    result["参加者统计量"] = participant_scores
    return result


def _select_gbt_rule(result: dict[str, Any], rule: str) -> None:
    """记录预选判据；缺少数据时不静默切换到另一判据。"""
    result["selected_rule"] = rule
    result["conclusion"] = result[f"{rule}_pass"]
    if result["conclusion"] is None:
        result["warnings"].append("预选主判据未评价，不得视为通过；须补足数据或审核设计")
    elif result["conclusion"] is False:
        result["warnings"].append("预选主判据未通过，须由授权人员审核并记录处置")


def calculate(data: dict[str, Any], review_mode: bool = False) -> dict[str, Any]:
    """根据输入选择 GL003 与 GL002 计算方法。"""
    if data.get("measurands"):
        return {
            "被测量": {
                name: calculate(part, review_mode=review_mode)
                for name, part in data["measurands"].items()
            }
        }
    cfg = data["config"]
    alpha = float(_option(cfg, "alpha", 0.05))
    sigma = criterion_sigma(cfg)
    if cfg.get("gbt28043_extension"):
        raise ValueError("旧配置 gbt28043_extension 不支持；请使用 criterion_standard")
    standard = _option(cfg, "criterion_standard", "gl003")
    if standard not in ENUMS["criterion_standard"]:
        raise InputError("criterion_standard 应为 gl003 或 gbt28043")
    delta_e = cfg.get("delta_e")
    delta_e = None if delta_e in (None, "") else delta_e
    basis_option = cfg.get("gbt_criterion_basis") or None
    basis = "sigma_pt"
    if standard == "gbt28043":
        basis, _ = gbt_criterion_limit(sigma, delta_e, basis_option)
    hom_rule = _option(cfg, "gbt_hom_rule", "basic")
    stab_rule = _option(cfg, "gbt_stability_rule", "basic")
    if standard == "gbt28043" and (
        hom_rule not in ENUMS["gbt_hom_rule"] or stab_rule not in ENUMS["gbt_stability_rule"]
    ):
        raise InputError("GB/T 判据应为 basic 或 extended")
    replicate_type = _option(cfg, "replicate_type", "technical")
    if replicate_type not in ENUMS["replicate_type"]:
        raise InputError("replicate_type 应为 technical、adjacent_specimens、other 或 single")
    result: dict[str, Any] = {}
    trend_input = data.get("trend_observations", [])
    trend_method = _option(cfg, "stability_method", "two_sample") == "regression_trend"
    if trend_method and not trend_input:
        raise InputError("回归趋势法须填写趋势稳定性数据")
    if trend_input and not trend_method:
        raise InputError("趋势稳定性须选择 regression_trend 方法")
    if trend_input:
        if not isinstance(_option(cfg, "trend_plot", False), bool):
            raise InputError("trend_plot 须为布尔值")
        if data.get("stability"):
            raise InputError("回归趋势法不能混用稳定性工作表")
        result["趋势稳定性"] = fit_series(
            trend_input, str(_option(cfg, "trend_aggregate", "per_series")), alpha
        )
        trend_u = configured_uncertainty(result["趋势稳定性"], cfg)
        if trend_u is not None:
            result["趋势不确定度"] = trend_u
    if cfg.get("design") == "transfer_standard":
        configs = data.get("transfer_config", {})
        if not configs:
            raise InputError("传递标准设计须登记逐点配置")
        result["传递标准稳定性"] = assess_transfer(data.get("transfer_observations", []), configs)
        result["传递标准汇总"] = summarize_transfer(result["传递标准稳定性"])
    elif data.get("transfer_observations") or data.get("transfer_config"):
        raise InputError("传递标准数据须选择 transfer_standard 设计")
    if data["homogeneity"]:
        strict = cfg.get("strict_homogeneity", False)
        if not isinstance(strict, bool):
            raise ValueError("strict_homogeneity 必须是布尔值")
        gl_criterion = _option(cfg, "gl003_hom_criterion", "f_test")
        if gl_criterion not in ENUMS["gl003_hom_criterion"]:
            raise InputError("GL003 均匀性判据应为 f_test、ss_0.3sigma 或 both")
        if strict:
            gl_criterion = "both"
        if replicate_type == "single":
            if gl_criterion == "both":
                raise InputError("单测设计不能使用要求 F 检验的严格配置")
            if not 0 < alpha < 1:
                raise InputError("alpha 必须在 0 和 1 之间")
            stage = _option(cfg, "sigma_stage", None)
            if stage is not None and stage not in ENUMS["sigma_stage"]:
                raise InputError("sigma 阶段应为 temporary 或 final")
            result["均匀性"] = single_homogeneity(data["homogeneity"], sigma)
            result["均匀性"]["sigma_source"] = _option(cfg, "sigma_source", None)
            result["均匀性"]["sigma_stage"] = stage if sigma is not None else None
            if sigma is not None and stage == "temporary":
                result["均匀性"]["Ss_status"] = "PROVISIONAL"
        else:
            result["均匀性"] = homogeneity(
                data["homogeneity"],
                sigma,
                alpha,
                strict,
                _option(cfg, "sigma_source", None),
                _option(cfg, "sigma_stage", None),
                gl_criterion,
            ).to_dict()
        if cfg.get("gl003_hom_criterion") not in (None, "") and replicate_type != "single":
            result["均匀性"]["selected_criterion"] = gl_criterion
        if replicate_type == "adjacent_specimens":
            result["均匀性"]["warnings"].append(
                "扩展提示：组内方差包含相邻试件之间的差异，可能低估样品间不均匀性"
            )
        if standard == "gbt28043":
            if replicate_type == "single":
                _, limit = gbt_criterion_limit(sigma, delta_e, basis_option)
                sx = result["均匀性"]["Ss"]
                gbt_hom = {
                    "g": len(data["homogeneity"]),
                    "m": 1,
                    "mean": result["均匀性"]["mean"],
                    "sx": sx,
                    "ss": sx,
                    "sigma": sigma,
                    "basic_limit": limit,
                    "basic_pass": compare(sx, limit) <= 0 if limit is not None else None,
                    "extended_limit": None,
                    "extended_pass": None,
                    "warnings": [
                        "B.1.2：单测标准差含测量误差，须选择重复性足够好的方法；扩展判据未评价"
                    ],
                }
            else:
                gbt_hom = gbt_homogeneity(
                    data["homogeneity"], sigma, delta_e=delta_e, basis=basis_option
                )
            _select_gbt_rule(gbt_hom, hom_rule)
            result["GB/T均匀性"] = gbt_hom
    groups = data["stability"]
    method = cfg.get("stability_method") or "two_sample"
    if groups:
        source = _option(
            cfg,
            "baseline_source",
            "homogeneity" if method == "mean_difference" else "baseline_group",
        )
        raw = cfg.get("reference")
        problem = stability_structure_problem(
            groups,
            method,
            source,
            bool(data["homogeneity"]),
            raw,
            standard,
            requires_reference=_option(cfg, "stability_design", "independent") == "independent"
            and _option(cfg, "reference_uncertainty_negligible", True) is True,
        )
        if problem:
            raise InputError(problem[1])
        baseline_data = data["homogeneity"] if source == "homogeneity" else groups.get("基线")
        reference = float(raw) if raw not in (None, "") else None
        if method == "mean_difference":
            if source == "homogeneity":
                reference = result["均匀性"]["mean"]
            else:
                reference = sum(sum(row) / len(row) for row in baseline_data) / len(baseline_data)
        level = _option(cfg, "observation_level", "unit_means")
        if level not in ENUMS["observation_level"]:
            raise ValueError("未知实验层级")
        if level == "all_repeats" and not review_mode:
            raise InputError("全部重复值仅供复核模型使用，不可用于常规结论")
        primary_group = (
            "稳定期" if "稳定期" in groups else next(name for name in groups if name != "基线")
        )
        if primary_group != "稳定期":
            result["稳定性时间组"] = primary_group
        design_options = {
            "design": _option(cfg, "stability_design", "independent"),
            "reference_uncertainty_negligible": _option(
                cfg, "reference_uncertainty_negligible", True
            ),
            "reference_source": source
            if method == "mean_difference"
            else _option(cfg, "reference_source", None),
        }
        result["稳定性"] = stability(
            groups.get("基线"),
            groups[primary_group],
            sigma,
            alpha,
            method,
            reference,
            group_name=primary_group,
            **design_options,
        ).to_dict()
        if level == "all_repeats":
            result["报告层级稳定性"] = stability(
                groups.get("基线"),
                groups[primary_group],
                sigma,
                alpha,
                method,
                reference,
                model="repeats_pooled",
                group_name=primary_group,
                **design_options,
            ).to_dict()
        extra = {}
        for name, observations in groups.items():
            if name not in ("基线", primary_group):
                extra[name] = stability(
                    groups.get("基线"),
                    observations,
                    sigma,
                    alpha,
                    method,
                    reference,
                    group_name=name,
                    **design_options,
                ).to_dict()
        if extra:
            result["其他稳定性"] = extra
        all_periods = [result["稳定性"], *extra.values()]
        if (
            method == "mean_difference"
            and groups.get("基线")
            and any(p.get("t") is not None for p in all_periods)
        ):
            baseline_mean = sum(sum(row) / len(row) for row in groups["基线"]) / len(groups["基线"])
            for period in all_periods:
                if period.get("t") is not None:
                    period["t_reference_baseline_mean"] = baseline_mean
                    period["t_reference_baseline_source"] = "稳定性表基线"
        if replicate_type == "adjacent_specimens" and method == "mean_difference":
            for period in [result["稳定性"], *extra.values()]:
                period["design_warnings"].append(
                    "GL003 5.3 注要求每个样品重复测试2次；相邻试件是破坏性检测的替代设计，须审核"
                )
                period["design_status"] = "DESIGN_WARNING"
        if standard == "gbt28043":
            if method not in ("two_sample", "mean_difference"):
                raise InputError("GB/T 28043 稳定性模式需要两组样品")
            settings = gbt_period_options(cfg, groups)
            independent = design_options["design"] == "independent"
            gbt_periods = {}
            for name, observations in groups.items():
                if name == "基线":
                    continue
                period = gbt_stability(
                    baseline_data,
                    observations,
                    sigma,
                    delta_e=delta_e,
                    basis=basis_option,
                    independent=independent,
                    allow_single_baseline=source == "homogeneity" and replicate_type == "single",
                    **settings[name],
                )
                if period["m2"] == 1:
                    period["warnings"].append(f"{name}组内重复性不可评价（单次测量）")
                if name != "稳定期" and settings[name]["u2"] is None:
                    period["warnings"].append("额外时点不复用稳定期均值不确定度；须分别评定")
                _select_gbt_rule(period, stab_rule)
                gbt_periods[name] = period
            result["GB/T稳定性"] = gbt_periods
    if data["participants"]:
        legacy_blocked = (
            standard == "gbt28043"
            and not data.get("assigned_config", {}).get("method")
            and (
                data.get("assigned_config", {}).get("stability_disposition") == "withhold"
                or any(
                    p.get("conclusion") is not True for p in result.get("GB/T稳定性", {}).values()
                )
            )
        )
        result.update(_participant_results(data, sigma, legacy_scores=not legacy_blocked))
        if legacy_blocked and cfg.get("assigned") not in (None, ""):
            result["参加者z状态"] = "DESIGN_REVIEW：稳定性未通过或未评价，须登记指定值和处置依据"
    if data.get("assigned_config", {}).get("method"):
        assignment_data = data
        if result.get("趋势不确定度"):
            assigned_config = dict(data["assigned_config"])
            if assigned_config.get("u_stab") not in (None, "", 0, 0.0):
                raise InputError("趋势 u_stab 与手工 u_stab 不可同时输入")
            assigned_config["u_stab"] = result["趋势不确定度"]["u_stab"]
            assignment_data = {**data, "assigned_config": assigned_config}
        result.update(
            _assigned_results(
                assignment_data,
                result,
                basis=basis,
                delta_e=delta_e if standard == "gbt28043" else None,
            )
        )
    if data.get("algorithm_s_values"):
        result["算法S"] = algorithm_s(
            data["algorithm_s_values"],
            data["algorithm_s_df"],
            max_iterations=int(_option(cfg, "algorithm_s_max_iterations", 1000)),
            stop_rule=str(_option(cfg, "algorithm_s_stop_rule", "gl002")),
            tolerance=float(_option(cfg, "algorithm_s_tolerance", 1e-12)),
        ).to_dict()
    if not result:
        raise ValueError("没有可计算的数据")
    if standard == "gbt28043":
        result["标准模式"] = standard
        if "均匀性" in result:
            result["均匀性"]["reference_only"] = True
        if "稳定性" in result:
            result["稳定性"]["reference_only"] = True
        for item in result.get("其他稳定性", {}).values():
            item["reference_only"] = True
        h = result.get("GB/T均匀性", {})
        result["主判据"] = {
            "standard": standard,
            "criterion_basis": basis,
            "delta_e": delta_e,
            "homogeneity_basic": h.get("basic_pass"),
            "homogeneity_extended": h.get("extended_pass"),
            "homogeneity_selected_rule": hom_rule,
            "homogeneity_conclusion": h.get("conclusion"),
            "stability": {
                name: {
                    "basic": s["basic_pass"],
                    "extended": s["extended_pass"],
                    "selected_rule": s["selected_rule"],
                    "conclusion": s["conclusion"],
                }
                for name, s in result.get("GB/T稳定性", {}).items()
            },
        }
    return result


def _parser() -> argparse.ArgumentParser:
    """创建带中文说明的命令行参数。"""
    parser = argparse.ArgumentParser(prog="openpt", description="能力验证统计工作台")
    parser.add_argument(
        "--version", action="version", version=f"openpt {__version__}", help="显示版本"
    )
    sub = parser.add_subparsers(dest="command", required=True, title="命令")
    t = sub.add_parser("template", help="生成空白 Excel 模板")
    t.add_argument("output", help="模板文件路径")
    sampling = sub.add_parser("sample", help="随机抽样及生成重复检测顺序")
    sampling.add_argument("--units", type=int, required=True, help="总体单元数")
    sampling.add_argument("--pick", type=int, required=True, help="抽样数")
    sampling.add_argument("--seed", type=int, required=True, help="非负随机种子")
    sampling.add_argument("--strata", help="分层 JSON 文件")
    sampling.add_argument("--output", default="sample-output", help="新的输出目录")
    decision = sub.add_parser("decide", help="追加人工决定并生成新版本计算书")
    decision.add_argument("directory", help="已有运行目录")
    decision.add_argument("--item", required=True, help="复核条目")
    decision.add_argument("--allow-new-item", action="store_true", help="允许登记结果之外的条目")
    decision.add_argument("--decision", required=True, choices=ENUMS["decision"])
    decision.add_argument("--by", required=True, dest="person", help="决定人员")
    decision.add_argument("--note", default="", help="决定备注")
    reproduction = sub.add_parser("reproduce", help="校验快照并重新计算")
    reproduction.add_argument("directory", help="已有运行目录")
    pack = sub.add_parser("pack", help="按 manifest.json 打包已有运行目录")
    pack.add_argument("directory", help="运行目录")
    pack.add_argument("-o", "--output", required=True, help="新的 ZIP 文件")
    verify = sub.add_parser("verify", help="检查 ZIP 中的清单和文件哈希")
    verify.add_argument("archive", help="审计包 ZIP")
    validate = sub.add_parser("validate", help="只读检查测量表并输出 JSON 问题清单")
    validate.add_argument("input", help="XLSX 或 CSV 文件")
    validate.add_argument("--columns", help="标准字段到原始列名的 JSON 映射")
    validate.add_argument(
        "--encoding", default="utf-8-sig", help="CSV 编码，默认 UTF-8（兼容 BOM）"
    )
    validate.add_argument("--sheet", default="均匀性", help="CSV 测量表类型")
    demo = sub.add_parser("demo", help="生成公开演示数据及计算结果")
    demo.add_argument("directory", help="示例输出目录")
    batch = sub.add_parser("review-batch", help="批量复核并输出 XLSX 差异总表")
    batch.add_argument("inputs", nargs="+", help="输入 Excel 文件")
    batch.add_argument("--output", required=True, help="差异总表 XLSX 路径")
    batch.add_argument("--mapping", help="可选 JSON 评分映射")
    for name in ("run", "review"):
        p = sub.add_parser(name, help="运行计算" if name == "run" else "复核报告")
        p.add_argument("input", help="输入 Excel 或 CSV 文件")
        p.add_argument("--columns", help="JSON 列映射文件")
        p.add_argument("--encoding", default="utf-8-sig", help="CSV 编码")
        p.add_argument("--csv-sheet", default="均匀性", help="CSV 对应的测量表")
        p.add_argument("--unit", help="CSV 测量单位，须明确提供")
        p.add_argument("--project", default="CSV 输入", help="CSV 项目名称")
        p.add_argument(
            "--runs-dir", default=os.environ.get("OPENPT_RUNS_DIR", "runs"), help="运行记录根目录"
        )
        p.add_argument("--sample-record", help="可选抽样记录文件，原样保存")
        p.add_argument("--docx", help="额外导出计算书路径；默认仅保存于运行目录")
        p.add_argument("--json", help="额外导出结果 JSON 路径；默认仅保存于运行目录")
        if name == "review":
            p.add_argument("--differences", help="额外导出差异 CSV 路径；默认仅保存于运行目录")
            p.add_argument("--mapping", help="可选 JSON 评分映射")
    return parser


def _deny_run_write(path: str | Path) -> None:
    """拒绝将普通输出写入任何已有运行目录。"""
    target = Path(path).resolve()
    if any((parent / "manifest.json").is_file() for parent in (target, *target.parents)):
        raise ValueError("不得修改已有运行目录")


def _validate_output_paths(args: argparse.Namespace) -> None:
    """防止输出文件覆盖输入、映射文件或彼此覆盖。"""
    outputs = [Path(value).resolve() for value in (args.docx, args.json) if value is not None]
    protected = {Path(args.input).resolve()}
    if args.columns:
        protected.add(Path(args.columns).resolve())
    if args.sample_record:
        protected.add(Path(args.sample_record).resolve())
    if args.command == "review":
        if args.differences is not None:
            outputs.append(Path(args.differences).resolve())
        if args.mapping:
            protected.add(Path(args.mapping).resolve())
    if len(set(outputs)) != len(outputs) or protected.intersection(outputs):
        raise ValueError("输出路径不得覆盖输入文件、映射文件或其他输出文件")
    if any(path.is_relative_to(Path(args.runs_dir).resolve()) for path in outputs):
        raise ValueError("常规输出不得写入运行记录根目录")
    for path in outputs:
        _deny_run_write(path)


def _configure_console() -> None:
    """控制台不支持中文时替换字符，重定向输出采用 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            if stream.isatty():
                reconfigure(errors="replace")
            else:
                reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # 嵌入式或测试捕获流可能不支持重新配置。
            continue


def _check_cli_paths(args: argparse.Namespace) -> None:
    """在转换为 Path 前拒绝空路径，并检查必须存在的输入。"""
    inputs = {
        "decide": ("directory",),
        "reproduce": ("directory",),
        "pack": ("directory",),
        "verify": ("archive",),
        "validate": ("input",),
        "run": ("input",),
        "review": ("input",),
    }
    names = list(inputs.get(args.command, ()))
    names.extend(
        name
        for name in ("columns", "mapping", "strata", "sample_record")
        if getattr(args, name, None) is not None
    )
    paths = [(name, getattr(args, name)) for name in names]
    if args.command == "review-batch":
        paths.extend(("input", value) for value in args.inputs)
    for name, value in paths:
        if not value or not str(value).strip():
            raise InputError(f"{name} 路径不能为空")
        if not Path(value).exists():
            raise InputError(f"{name} 路径不存在：{value}")
    output_names = ["output", "docx", "json", "differences", "runs_dir"]
    if args.command == "demo":
        output_names.append("directory")
    for name in output_names:
        value = getattr(args, name, None)
        if value is not None and (not value or not str(value).strip()):
            raise InputError(f"{name} 路径不能为空")


def main(argv: list[str] | None = None) -> int:
    """执行模板、计算或复核命令，返回进程退出码。"""
    _configure_console()
    args = _parser().parse_args(argv)
    try:
        _check_cli_paths(args)
        if args.command == "template":
            _deny_run_write(args.output)
            template(args.output)
            return 0
        if args.command == "sample":
            from .sampling import sample, write_sample

            strata = (
                json.loads(Path(args.strata).read_text(encoding="utf-8")) if args.strata else None
            )
            if strata is not None and not isinstance(strata, dict):
                raise ValueError("分层必须是 JSON 对象")
            record = sample(args.units, args.pick, args.seed, strata)
            _deny_run_write(args.output)
            write_sample(args.output, record)
            for warning in record["warnings"]:
                print(warning)
            return 0
        if args.command == "decide":
            from .decisions import decide

            decide(
                Path(args.directory),
                args.item,
                args.decision,
                args.person,
                args.note,
                allow_new_item=args.allow_new_item,
            )
            print("已记录人工决定；软件不自动放行。")
            return 0
        if args.command == "reproduce":
            from .runs import reproduce

            try:
                audit_differences, warnings = reproduce(Path(args.directory))
            except (ValueError, TypeError, OSError, KeyError, OverflowError, BadZipFile):
                print("不可重现：清单、配置或输入无法读取或无效")
                return 1
            for item in warnings:
                print(f"环境版本不同：{item}")
            print("不可重现" if audit_differences else "可重现")
            for difference in audit_differences:
                print(difference)
            return 1 if audit_differences else 0
        if args.command == "pack":
            from .audit import pack_directory

            _deny_run_write(args.output)
            pack_directory(args.directory, args.output)
            return 0
        if args.command == "verify":
            from .audit import verify_zip

            audit_differences = verify_zip(args.archive)
            print(
                "\n".join(audit_differences)
                if audit_differences
                else "清单哈希一致（未验证清单真实性）"
            )
            return 1 if audit_differences else 0
        if args.command == "validate":
            from .io.validation import inspect_input

            columns = (
                json.loads(Path(args.columns).read_text(encoding="utf-8")) if args.columns else {}
            )
            if not isinstance(columns, dict):
                raise ValueError("列映射必须为 JSON 对象")
            issues = inspect_input(
                args.input, columns, encoding=args.encoding, csv_sheet=args.sheet
            )
            print(
                json.dumps([issue.to_dict() for issue in issues], ensure_ascii=False, default=str)
            )
            return 1 if issues else 0
        if args.command == "demo":
            from .demo import create_demo

            create_demo(Path(args.directory))
            return 0
        if args.command == "review-batch":
            from .review.batch import batch_review, write_xlsx

            protected = {Path(path).resolve() for path in args.inputs}
            if args.mapping:
                protected.add(Path(args.mapping).resolve())
            if Path(args.output).resolve() in protected:
                raise ValueError("输出路径不得覆盖输入或映射")
            _deny_run_write(args.output)
            mapping = (
                json.loads(Path(args.mapping).read_text(encoding="utf-8")) if args.mapping else None
            )
            if mapping is not None and not isinstance(mapping, dict):
                raise ValueError("评分映射必须是 JSON 对象")
            write_xlsx(args.output, batch_review(args.inputs, mapping))
            return 0
        _validate_output_paths(args)
        from .runs import create_run

        _deny_run_write(args.runs_dir)
        directory, data, result, differences, digest = create_run(args, Path(args.runs_dir))
        print(f"运行记录：{directory}")
        print(f"计算书：{directory / 'report.docx'}")
        print(f"结果 JSON：{directory / 'result.json'}")
        if differences is not None:
            print(f"差异表：{directory / 'differences.csv'}")
            if args.differences is not None:
                from .review.compare import write_csv

                write_csv(args.differences, differences)
                print(f"额外差异表：{args.differences}")
        if args.json is not None:
            Path(args.json).write_text(
                json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            print(f"额外结果 JSON：{args.json}")
        if args.docx is not None:
            make_report(args.docx, data, result, differences, input_sha256=digest)
            print(f"额外计算书：{args.docx}")
        return 0
    except OSError as exc:
        print(f"错误：文件操作失败（{exc.strerror or '系统错误'}）", file=sys.stderr)
        return 2
    except (ValueError, TypeError, KeyError, OverflowError, BadZipFile) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
