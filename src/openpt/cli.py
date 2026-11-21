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
from .config.rules import check_assigned, check_cross, check_method_config, check_period_groups
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
from .errors import InputError, format_error, locate, sheet_call
from .formatting import significant
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
        raise InputError(
            "stability_disposition 应为 pending、budgeted、reviewed 或 withhold",
            field="stability_disposition",
            allowed="pending、budgeted、reviewed 或 withhold",
            hint="选择有效处置",
        )
    if not isinstance(reason, str):
        raise InputError(
            "稳定性处置依据须为文字",
            field="stability_disposition_reason",
            allowed="文字",
            hint="填写书面依据",
        )
    flagged = {name: p for name, p in periods.items() if p.get("conclusion") is not True}
    if disposition in ("budgeted", "reviewed") and flagged and not reason.strip():
        raise InputError(
            "稳定性处置须登记书面依据",
            field="stability_disposition_reason",
            allowed="非空文字",
            hint="填写授权审核的书面依据",
        )
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
            raise InputError(
                "稳定性或运输影响尚未登记到不确定度预算；不得凭均值差自动估算",
                fields=[
                    "u_stab",
                    "stab_mapping",
                    "stab_in_base",
                    "u_trans",
                    "trans_mapping",
                    "trans_in_base",
                    "trans_in_stab",
                ],
                hint="审核并登记稳定性及运输不确定度预算",
            )
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
                    raise InputError(
                        "transfer_en_map 含重复参加者编号",
                        sheet="方法配置",
                        field="transfer_en_map",
                        hint="删除重复编号",
                    )
                output[item_key] = value
            return output

        try:
            mapping = (
                json.loads(raw, object_pairs_hook=unique_pairs) if isinstance(raw, str) else raw
            )
        except ValueError:
            raise InputError(
                "transfer_en_map 须为有效 JSON 对象",
                sheet="方法配置",
                field="transfer_en_map",
                allowed="JSON 对象",
                hint="修正 JSON 格式",
            ) from None
        if not isinstance(mapping, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()
        ):
            raise InputError(
                "transfer_en_map 须将参加者编号映射到标准器|校准点",
                sheet="方法配置",
                field="transfer_en_map",
                allowed="字符串到字符串的 JSON 对象",
                hint="逐个登记参加者与校准点",
            )
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
            raise InputError(
                "参考值扩展不确定度须为非负有限数",
                field="U_assigned",
                allowed="非负有限数",
                hint="修改扩展不确定度",
            )
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
        raise InputError(
            "hom_source 应为 manual 或 gbt_ss", field="hom_source", allowed="manual 或 gbt_ss"
        )
    if hom_source == "gbt_ss":
        if _option(data["config"], "criterion_standard", "gl003") != "gbt28043":
            raise InputError(
                "从标准模式引用 ss 须选择 gbt28043",
                sheet="方法配置",
                field="criterion_standard",
                allowed="gbt28043",
            )
        h = calculations.get("GB/T均匀性")
        if not h:
            raise InputError("引用 ss 须提供均匀性数据", sheet="均匀性")
        if a.get("hom_mapping") not in ("assigned", "sigma_prime", "both"):
            raise InputError(
                "引用 ss 须明确登记分量映射",
                field="hom_mapping",
                allowed="assigned、sigma_prime 或 both",
            )
        if a.get("u_hom") not in (None, "", 0, 0.0):
            raise InputError("引用 ss 时不得同时手工输入 u_hom", field="u_hom", hint="清空手工值")
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
                raise InputError(
                    f"{key} 须为逗号分隔的数值列表", field=key, hint="填写逗号分隔数值"
                )
            try:
                options[key] = [float(item.strip()) for item in a[key].split(",")]
            except ValueError:
                raise InputError(
                    f"{key} 须为逗号分隔的数值列表", field=key, hint="填写逗号分隔数值"
                ) from None
    assigned = sheet_call(
        "参加者结果",
        assign_value,
        a["method"],
        participants=[p["value"] for p in data["participants"]],
        **options,
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
                score_result = sheet_call(
                    "参加者结果",
                    performance_score,
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


def _unevaluated_reason(item: dict[str, Any], fallback: str) -> str:
    """优先采用结果已登记的原因、警告及非正常状态。"""
    reason = item.get("reason")
    warnings = item.get("warnings") or item.get("design_warnings") or []
    if isinstance(warnings, str):
        warnings = [warnings]
    parts = [str(reason)] if reason else []
    parts.extend(str(warning) for warning in warnings if warning and str(warning) not in parts)
    if item.get("status") == "INDETERMINATE" and item.get("b1") == 0 and item.get("s_b1") == 0:
        parts.append("斜率和斜率标准误均为零，无法进行趋势显著性判定")
    if item.get("status") == "INDETERMINATE" and item.get("se") == 0 and item.get("t") is None:
        parts.append("标准误为零，t 统计量无法计算")
    status = item.get("status")
    if status and status != "OK":
        parts.append(f"状态 {status}")
    detail = item.get("detail")
    if isinstance(detail, dict):
        nested = _unevaluated_reason(detail, "")
        if nested:
            parts.append(nested)
    return "；".join(parts) if parts else fallback


def _trend_transfer_diagnostics(
    data: dict[str, Any], result: dict[str, Any]
) -> list[dict[str, str]]:
    """从趋势与传递标准结果提取原因；缺少证据时不臆测数值。"""
    diagnostics: list[dict[str, str]] = []
    display_config = data.get("_diagnostic_config", data.get("config", {}))
    digits = int(_option(display_config, "display_sig_digits", 6))
    trends = result.get("趋势稳定性", {})
    for name, trend in trends.items():
        if trend.get("stable") is None:
            reason = _unevaluated_reason(trend, "结果未提供具体原因")
            diagnostics.append(
                {
                    "类型": "趋势未评价",
                    "层级": "根因",
                    "说明": f"趋势序列 {name} 未评价：{reason}；"
                    "请检查『趋势稳定性』的时间 X、值 Y 及重复测量数据。",
                }
            )
    assigned = data.get("assigned_config", {})
    if (
        trends
        and assigned.get("method")
        and not result.get("趋势不确定度")
        and not assigned.get("u_stab")
        and not assigned.get("stab_in_base")
    ):
        diagnostics.append(
            {
                "类型": "趋势不确定度未登记",
                "层级": "根因",
                "说明": "趋势计算未登记 u_stab 来源；如需将趋势纳入预算，请在『方法配置』填写 "
                "trend_short_series、trend_short_span、trend_long_series、trend_long_span，"
                "或在『指定值与不确定度』登记评定后的 u_stab 及 stab_mapping。",
            }
        )
    for name, point in result.get("传递标准稳定性", {}).items():
        if point.get("conclusion") is not True:
            criteria = [
                criterion
                for criterion in point.get("criteria", [])
                if criterion.get("pass") is not True
            ]
            details = []
            for criterion in criteria:
                reason = _unevaluated_reason(criterion, "")
                kind = criterion.get("kind", "未知")
                if criterion.get("pass") is False:
                    value = significant(criterion.get("value"), digits)
                    limit = significant(criterion.get("limit"), digits)
                    reason = f"判据 {kind} 未通过（统计量 {value}，限值 {limit}）" + (
                        f"；{reason}" if reason else ""
                    )
                elif reason:
                    reason = f"判据 {kind} 未评价：{reason}"
                else:
                    reason = f"判据 {kind} 未评价，结果未提供具体原因"
                details.append(reason)
            reason = "；".join(details) or _unevaluated_reason(point, "结果未提供具体原因")
            diagnostics.append(
                {
                    "类型": "传递标准未通过或未评价",
                    "层级": "根因",
                    "说明": f"传递标准 {name} 未通过或未评价：{reason}；"
                    "请检查『传递标准复测』的测量组、区间数据及『传递标准配置』的判据JSON。",
                }
            )
        if point.get("uncertainty_status") == "NOT_EVALUATED":
            diagnostics.append(
                {
                    "类型": "传递标准不确定度未登记",
                    "层级": "根因",
                    "说明": f"传递标准 {name} 的稳定性不确定度机制未登记；"
                    "如需用于 En，请在『传递标准配置』不确定度JSON 登记 mechanism 和 source。",
                }
            )
    return diagnostics


def _sigma_advice(data: dict[str, Any]) -> str:
    """按实际指定值路径给出 σ_pt 配置位置。"""
    if data.get("assigned_config", {}).get("method"):
        return (
            "请在『指定值与不确定度』登记正的 sigma_final 或 sigma_temporary 及 sigma_procedure。"
        )
    return "请在『方法配置』填写正的 sigma_pt 或 sigma；只填一个时会互相沿用。"


def _select_gbt_rule(result: dict[str, Any], rule: str) -> None:
    """记录预选判据；缺少数据时不静默切换到另一判据。"""
    result["selected_rule"] = rule
    result["conclusion"] = result[f"{rule}_pass"]
    if result["conclusion"] is None:
        result["warnings"].append("预选主判据未评价，不得视为通过；须补足数据或审核设计")
    elif result["conclusion"] is False:
        result["warnings"].append("预选主判据未通过，须由授权人员审核并记录处置")


def _gbt_extended_diagnostics(
    data: dict[str, Any], result: dict[str, Any], basis: str
) -> tuple[list[dict[str, str]], set[str]]:
    """说明预选扩展判据缺少输入或不适用的具体原因。"""
    diagnostics: list[dict[str, str]] = []
    explained: set[str] = set()
    hom = result.get("GB/T均匀性") or {}
    if hom.get("selected_rule") == "extended" and hom.get("conclusion") is None:
        reasons = []
        hom_basis = hom.get("criterion_basis", basis)
        if hom_basis == "delta_e":
            reasons.append("δE 依据不适用 B.2.3 扩展判据")
        if hom.get("m") == 1:
            reasons.append("单测设计不提供 B.2.3 扩展判据")
        elif hom.get("f1") is None:
            reasons.append(f"样品数 g={hom.get('g')} 不在表 B.1 的 7 至 20 范围内")
        if hom.get("sigma") is None and hom_basis != "delta_e":
            reasons.append("缺少判据 sigma，请在『方法配置』sigma 填写正值")
        if reasons:
            diagnostics.append(
                {
                    "类型": "扩展判据未评价",
                    "层级": "根因",
                    "说明": "均匀性选择了扩展判据（全局设置），未评价："
                    + "；".join(reasons)
                    + "；请审核方法及数据；如不需要扩展判据，"
                    "可在『方法配置』gbt_hom_rule 改用 basic。",
                }
            )
            explained.add("均匀性")
    for name, period in result.get("GB/T稳定性", {}).items():
        if period.get("selected_rule") != "extended" or period.get("conclusion") is not None:
            continue
        settings = period.get("criterion_settings") or {}
        origin = settings.get("rule", {}).get("source") or "全局设置"
        reasons = []
        if period.get("criterion_basis") == "delta_e":
            reasons.append("δE 依据不适用 B.5.2 扩展判据")
        elif period.get("sigma") is None:
            reasons.append("缺少判据 sigma，请在『方法配置』sigma 填写正值")
        if (data.get("config", {}).get("stability_design") or "independent") != "independent":
            reasons.append(
                "相关或配对设计不适用独立样品扩展判据，"
                "请审核『方法配置』stability_design 及实验设计"
            )
        if period.get("u1") is None:
            reasons.append("缺少 u1，请在『方法配置』stability_u1 填写基线均值标准不确定度")
        if period.get("u2") is None:
            advice = (
                "缺少 u2，请在『稳定性时间组配置』u2 列或逐时点 JSON 的 u2 填写后续均值标准不确定度"
            )
            if name == "稳定期":
                advice += "，也可在『方法配置』stability_u2 填写"
            reasons.append(advice)
        if reasons:
            diagnostics.append(
                {
                    "类型": "扩展判据未评价",
                    "层级": "根因",
                    "说明": f"稳定性（{name}）选择了扩展判据（{origin}），未评价："
                    + "；".join(reasons)
                    + "；如不需要扩展判据，可改用 basic。",
                }
            )
            explained.add(f"稳定性（{name}）")
    return diagnostics, explained


def calculate(data: dict[str, Any], review_mode: bool = False) -> dict[str, Any]:
    """计算并为结构化输入错误补充来源位置。"""
    try:
        return _calculate(data, review_mode)
    except InputError as exc:
        located = locate(exc, data)
        if located is exc:
            raise
        raise located from None


def _calculate(data: dict[str, Any], review_mode: bool = False) -> dict[str, Any]:
    """根据输入选择 GL003 与 GL002 计算方法。"""
    if data.get("measurands"):
        return {
            "被测量": {
                name: calculate(part, review_mode=review_mode)
                for name, part in data["measurands"].items()
            }
        }
    cfg = data["config"]
    assignment = data.get("assigned_config", {})
    rule_groups = (
        (
            "方法配置",
            check_method_config(cfg)
            + check_period_groups(cfg, data["stability"])
            + check_cross(assignment, cfg),
        ),
        ("指定值与不确定度", check_assigned(assignment, cfg)),
    )
    problems = []
    for sheet, rule_issues in rule_groups:
        for issue in rule_issues:
            cell, value = data.get("_cells", {}).get((sheet, issue.field), ("", issue.value))
            problems.append(
                {
                    "sheet": sheet,
                    "cell": cell,
                    "original": value,
                    "code": issue.code,
                    "field": issue.field,
                    "message": f"{issue.field}：{issue.message}；允许值/要求：{issue.allowed}；"
                    f"修改建议：{issue.hint}",
                }
            )
    if problems:
        if len(problems) == 1:
            sheet, rules = next((sheet, rules) for sheet, rules in rule_groups if rules)
            issue = rules[0]
            raise InputError(
                issue.message,
                sheet=sheet,
                field=issue.field,
                allowed=issue.allowed,
                hint=issue.hint,
                value=issue.value,
                issues=problems,
            )
        raise InputError(
            format_error(
                InputError("输入校验问题：" + json.dumps(problems, ensure_ascii=False, default=str))
            ),
            issues=problems,
            sheet="方法配置与指定值与不确定度",
        )
    alpha = float(_option(cfg, "alpha", 0.05))
    sigma = criterion_sigma(cfg)
    if cfg.get("gbt28043_extension"):
        raise ValueError("旧配置 gbt28043_extension 不支持；请使用 criterion_standard")
    standard = _option(cfg, "criterion_standard", "gl003")
    if standard not in ENUMS["criterion_standard"]:
        raise InputError(
            "criterion_standard 应为 gl003 或 gbt28043",
            sheet="方法配置",
            field="criterion_standard",
            allowed="gl003 或 gbt28043",
        )
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
        raise InputError(
            "GB/T 判据应为 basic 或 extended",
            sheet="方法配置",
            fields=["gbt_hom_rule", "gbt_stability_rule"],
            allowed="basic 或 extended",
        )
    replicate_type = _option(cfg, "replicate_type", "technical")
    if replicate_type not in ENUMS["replicate_type"]:
        raise InputError(
            "replicate_type 应为 technical、adjacent_specimens、other 或 single",
            sheet="方法配置",
            field="replicate_type",
            allowed="technical、adjacent_specimens、other 或 single",
        )
    result: dict[str, Any] = {}
    trend_input = data.get("trend_observations", [])
    trend_method = _option(cfg, "stability_method", "two_sample") == "regression_trend"
    if trend_method and not trend_input:
        raise InputError("回归趋势法须填写趋势稳定性数据", sheet="趋势稳定性")
    if trend_input and not trend_method:
        raise InputError(
            "趋势稳定性须选择 regression_trend 方法",
            sheet="方法配置",
            field="stability_method",
            allowed="regression_trend",
            hint="修改稳定性方法",
        )
    if trend_input:
        if not isinstance(_option(cfg, "trend_plot", False), bool):
            raise InputError(
                "trend_plot 须为布尔值",
                sheet="方法配置",
                field="trend_plot",
                allowed="TRUE 或 FALSE",
            )
        if data.get("stability"):
            raise InputError("回归趋势法不能混用稳定性工作表", sheet="稳定性")
        result["趋势稳定性"] = sheet_call(
            "趋势稳定性",
            fit_series,
            trend_input,
            str(_option(cfg, "trend_aggregate", "per_series")),
            alpha,
        )
        trend_u = sheet_call("趋势稳定性", configured_uncertainty, result["趋势稳定性"], cfg)
        if trend_u is not None:
            result["趋势不确定度"] = trend_u
    if cfg.get("design") == "transfer_standard":
        configs = data.get("transfer_config", {})
        if not configs:
            raise InputError("传递标准设计须登记逐点配置", sheet="传递标准配置")
        result["传递标准稳定性"] = sheet_call(
            "传递标准配置", assess_transfer, data.get("transfer_observations", []), configs
        )
        result["传递标准汇总"] = summarize_transfer(result["传递标准稳定性"])
    elif data.get("transfer_observations") or data.get("transfer_config"):
        raise InputError(
            "传递标准数据须选择 transfer_standard 设计",
            sheet="方法配置",
            field="design",
            allowed="transfer_standard",
        )
    if data["homogeneity"]:
        strict = cfg.get("strict_homogeneity", False)
        if not isinstance(strict, bool):
            raise ValueError("strict_homogeneity 必须是布尔值")
        gl_criterion = _option(cfg, "gl003_hom_criterion", "f_test")
        if gl_criterion not in ENUMS["gl003_hom_criterion"]:
            raise InputError(
                "GL003 均匀性判据应为 f_test、ss_0.3sigma 或 both",
                sheet="方法配置",
                field="gl003_hom_criterion",
                allowed="f_test、ss_0.3sigma 或 both",
            )
        if strict:
            gl_criterion = "both"
        if replicate_type == "single":
            if strict or cfg.get("gl003_hom_criterion") not in (None, ""):
                raise InputError(
                    "单测采用 GB/T 28043-2019 B.1.2 单测标准差法，不支持 GL003 4.2/4.3 "
                    "主判据或严格配置；请清空 gl003_hom_criterion 并关闭 strict_homogeneity",
                    sheet="方法配置",
                    fields=["gl003_hom_criterion", "strict_homogeneity"],
                )
            if not 0 < alpha < 1:
                raise InputError(
                    "alpha 必须在 0 和 1 之间",
                    sheet="方法配置",
                    field="alpha",
                    allowed="0 < alpha < 1",
                )
            stage = _option(cfg, "sigma_stage", None)
            if stage is not None and stage not in ENUMS["sigma_stage"]:
                raise InputError(
                    "sigma 阶段应为 temporary 或 final",
                    sheet="方法配置",
                    field="sigma_stage",
                    allowed="temporary 或 final",
                )
            result["均匀性"] = sheet_call("均匀性", single_homogeneity, data["homogeneity"], sigma)
            result["均匀性"]["sigma_source"] = _option(cfg, "sigma_source", None)
            result["均匀性"]["sigma_stage"] = stage if sigma is not None else None
            if sigma is not None and stage == "temporary":
                result["均匀性"]["Ss_status"] = "PROVISIONAL"
        else:
            result["均匀性"] = sheet_call(
                "均匀性",
                homogeneity,
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
                gbt_hom = sheet_call(
                    "均匀性",
                    gbt_homogeneity,
                    data["homogeneity"],
                    sigma,
                    delta_e=delta_e,
                    basis=basis_option,
                )
            _select_gbt_rule(gbt_hom, hom_rule)
            result["GB/T均匀性"] = gbt_hom
    groups = data["stability"]
    method = cfg.get("stability_method") or "two_sample"
    raw_periods = cfg.get("stability_period_options") or {}
    periods = json.loads(raw_periods) if isinstance(raw_periods, str) else raw_periods
    if set(periods) - (set(groups) - {"基线"}):
        raise InputError(
            "逐时点配置包含不存在的时间组", sheet="方法配置", field="stability_period_options"
        )
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
        if problem and not any(
            "stability_method" in entry or "baseline_source" in entry for entry in periods.values()
        ):
            raise InputError(problem[1], sheet="稳定性")
        baseline_data = data["homogeneity"] if source == "homogeneity" else groups.get("基线")
        reference = float(raw) if raw not in (None, "") else None
        if method == "mean_difference":
            if source == "homogeneity" and result.get("均匀性"):
                reference = result["均匀性"]["mean"]
            elif baseline_data:
                reference = sum(sum(row) / len(row) for row in baseline_data) / len(baseline_data)
        level = _option(cfg, "observation_level", "unit_means")
        if level not in ENUMS["observation_level"]:
            raise ValueError("未知实验层级")
        if level == "all_repeats" and not review_mode:
            raise InputError(
                "全部重复值仅供复核模型使用，不可用于常规结论",
                sheet="方法配置",
                field="observation_level",
            )
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

        use_group_criteria = any(
            set(entry) & {"stability_method", "baseline_source"} for entry in periods.values()
        )

        def group_settings(name: str) -> dict[str, Any]:
            entry = periods.get(name, {})

            def choose(key: str, global_key: str | None, default: Any) -> dict[str, Any]:
                if key in entry:
                    return {"value": entry[key], "source": "逐组设置"}
                if global_key and cfg.get(global_key) not in (None, ""):
                    explicit = data.get("_diagnostic_config", cfg).get(global_key) not in (None, "")
                    return {
                        "value": cfg[global_key],
                        "source": "全局设置" if explicit else "方法默认",
                    }
                return {"value": default, "source": "方法默认"}

            group_method = choose("stability_method", "stability_method", "two_sample")
            group_source = choose(
                "baseline_source",
                "baseline_source",
                "homogeneity" if group_method["value"] == "mean_difference" else "baseline_group",
            )
            if (
                standard == "gl003"
                and not use_group_criteria
                and group_method["value"] == "two_sample"
                and group_source["value"] != "baseline_group"
            ):
                # 旧两样本计算实际固定使用稳定性基线组，保留原数值并如实登记。
                group_source = {"value": "baseline_group", "source": "方法默认"}
            return {
                "stability_method": group_method,
                "baseline_source": group_source,
                "rule": choose("rule", "gbt_stability_rule", "basic"),
                "basis": choose("basis", "gbt_criterion_basis", basis),
                "delta_e": choose("delta_e", "delta_e", None),
                "kind": choose("kind", None, "storage"),
                "u2": choose("u2", "stability_u2" if name == "稳定期" else None, None),
            }

        def calculate_group(name: str, *, model: str = "unit_pooled") -> Any:
            resolved = group_settings(name)
            selected_method = resolved["stability_method"]["value"]
            selected_source = resolved["baseline_source"]["value"]
            group_shape = set(groups)
            if use_group_criteria:
                group_shape.add("稳定期")
                if selected_source == "homogeneity" and data["homogeneity"]:
                    group_shape.add("基线")
            problem = stability_structure_problem(
                group_shape,
                selected_method,
                selected_source,
                bool(data["homogeneity"]),
                raw,
                standard,
                requires_reference=_option(cfg, "stability_design", "independent") == "independent"
                and _option(cfg, "reference_uncertainty_negligible", True) is True,
            )
            if problem:
                raise InputError(problem[1], sheet="方法配置", field="stability_period_options")
            selected_baseline = (
                data["homogeneity"] if selected_source == "homogeneity" else groups.get("基线")
            )
            selected_reference = float(raw) if raw not in (None, "") else None
            if selected_method == "mean_difference":
                selected_reference = (
                    reference
                    if selected_method == method and selected_source == source
                    else sum(sum(row) / len(row) for row in selected_baseline)
                    / len(selected_baseline)
                )
            options = {
                **design_options,
                "reference_source": selected_source
                if selected_method == "mean_difference"
                else _option(cfg, "reference_source", None),
            }
            calculated = sheet_call(
                "稳定性",
                stability,
                selected_baseline if use_group_criteria else groups.get("基线"),
                groups[name],
                sigma,
                alpha,
                selected_method,
                selected_reference,
                model=model,
                group_name=name,
                **options,
            ).to_dict()
            calculated["criterion_settings"] = resolved
            return calculated

        result["稳定性"] = calculate_group(primary_group)
        if level == "all_repeats":
            result["报告层级稳定性"] = calculate_group(primary_group, model="repeats_pooled")
        extra = {}
        for name in groups:
            if name not in ("基线", primary_group):
                extra[name] = calculate_group(name)
        if extra:
            result["其他稳定性"] = extra
        all_periods = [result["稳定性"], *extra.values()]
        if groups.get("基线") and any(p.get("t") is not None for p in all_periods):
            baseline_mean = sum(sum(row) / len(row) for row in groups["基线"]) / len(groups["基线"])
            for period in all_periods:
                if period.get("method") == "mean_difference" and period.get("t") is not None:
                    period["t_reference_baseline_mean"] = baseline_mean
                    period["t_reference_baseline_source"] = "稳定性表基线"
        if replicate_type == "adjacent_specimens":
            for period in [result["稳定性"], *extra.values()]:
                if period.get("method") != "mean_difference":
                    continue
                period["design_warnings"].append(
                    "GL003 5.3 注要求每个样品重复测试2次；相邻试件是破坏性检测的替代设计，须审核"
                )
                period["design_status"] = "DESIGN_WARNING"
        if standard == "gbt28043":
            if method not in ("two_sample", "mean_difference"):
                raise InputError(
                    "GB/T 28043 稳定性模式需要两组样品", sheet="方法配置", field="stability_method"
                )
            settings = sheet_call("稳定性", gbt_period_options, cfg, groups)
            independent = design_options["design"] == "independent"
            gbt_periods = {}
            for name, observations in groups.items():
                if name == "基线":
                    continue
                period = sheet_call(
                    "稳定性",
                    gbt_stability,
                    data["homogeneity"]
                    if group_settings(name)["baseline_source"]["value"] == "homogeneity"
                    else groups.get("基线"),
                    observations,
                    sigma,
                    delta_e=group_settings(name)["delta_e"]["value"],
                    basis=(
                        None
                        if group_settings(name)["basis"]["source"] == "方法默认"
                        else group_settings(name)["basis"]["value"]
                    ),
                    independent=independent,
                    allow_single_baseline=group_settings(name)["baseline_source"]["value"]
                    == "homogeneity"
                    and replicate_type == "single",
                    **settings[name],
                )
                if period["m2"] == 1:
                    period["warnings"].append(f"{name}组内重复性不可评价（单次测量）")
                if name != "稳定期" and settings[name]["u2"] is None:
                    period["warnings"].append("额外时点不复用稳定期均值不确定度；须分别评定")
                resolved = group_settings(name)
                resolved["basis"]["value"] = period["criterion_basis"]
                _select_gbt_rule(period, resolved["rule"]["value"])
                period["criterion_settings"] = resolved
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
        result.update(
            sheet_call(
                "参加者结果", _participant_results, data, sigma, legacy_scores=not legacy_blocked
            )
        )
        if legacy_blocked and cfg.get("assigned") not in (None, ""):
            result["参加者z状态"] = "DESIGN_REVIEW：稳定性未通过或未评价，须登记指定值和处置依据"
    if data.get("assigned_config", {}).get("method"):
        assignment_data = data
        if result.get("趋势不确定度"):
            assigned_config = dict(data["assigned_config"])
            if assigned_config.get("u_stab") not in (None, "", 0, 0.0):
                raise InputError(
                    "趋势 u_stab 与手工 u_stab 不可同时输入",
                    field="u_stab",
                    hint="清空手工 u_stab 或移除趋势不确定度配置",
                )
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
        result["算法S"] = sheet_call(
            "算法S",
            algorithm_s,
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
    diagnostics: list[dict[str, str]] = []
    for field in ("display_mean_decimals", "display_ss_decimals"):
        if cfg.get(field) not in (None, ""):
            diagnostics.append(
                {
                    "类型": "显示配置",
                    "层级": "提示",
                    "说明": f"『方法配置』{field} 已废弃并忽略，"
                    "改用 display_value_decimals 或 display_sig_digits。",
                }
            )
    assigned_config = data.get("assigned_config", {})
    unevaluated: list[str] = []
    hom_result = result.get("GB/T均匀性") if standard == "gbt28043" else result.get("均匀性")
    if hom_result and hom_result.get("conclusion") is None:
        unevaluated.append("均匀性")
    if standard == "gbt28043":
        periods = result.get("GB/T稳定性", {})
    else:
        periods = dict(result.get("其他稳定性", {}))
        if result.get("稳定性"):
            periods[result.get("稳定性时间组", "稳定期")] = result["稳定性"]
    for name, period in periods.items():
        conclusion_key = (
            "conclusion"
            if standard == "gbt28043"
            else "mean_difference_pass"
            if period.get("method") == "mean_difference"
            else "pass"
        )
        if period.get(conclusion_key) is None:
            unevaluated.append(f"稳定性（{name}）")
    explained: set[str] = set()
    if standard == "gbt28043":
        specific, explained = _gbt_extended_diagnostics(data, result, basis)
        diagnostics.extend(specific)
    missing = (basis == "sigma_pt" and sigma is None) or (basis == "delta_e" and delta_e is None)
    sigma_items: list[str] = []
    if standard == "gbt28043":
        if (
            hom_result
            and hom_result.get("conclusion") is None
            and hom_result.get("criterion_basis", basis) == basis
        ):
            sigma_items.append("均匀性")
        sigma_items.extend(
            f"稳定性（{name}）"
            for name, period in periods.items()
            if period.get("conclusion") is None and period.get("criterion_basis") == basis
        )
    else:
        if (
            hom_result
            and hom_result.get("conclusion") is None
            and hom_result.get("selected_criterion") in ("ss_0.3sigma", "both")
        ):
            sigma_items.append("均匀性")
        sigma_items.extend(
            f"稳定性（{name}）"
            for name, period in periods.items()
            if period.get("method") == "mean_difference"
            and period.get("mean_difference_pass") is None
        )
    if sigma_items and missing:
        field = "sigma" if basis == "sigma_pt" else "delta_e"
        message = f"{'、'.join(sigma_items)}未评价；『方法配置』判据 {field} 未填写，请填写判据。"
        if field == "sigma" and any(
            assigned_config.get(key) not in (None, "") for key in ("sigma_final", "sigma_temporary")
        ):
            message += (
                "指定值表中的 sigma_final/sigma_temporary 仅作为 σ_pt 用于 z 等统计量，"
                "不作为均匀性或稳定性判据；如需同值请在『方法配置』sigma 填写。"
            )
        diagnostics.append({"类型": "判据缺失", "层级": "根因", "说明": message})
    others = [
        item
        for item in unevaluated
        if item not in explained and not (missing and item in sigma_items)
    ]
    if others:
        diagnostics.append(
            {"类型": "未评价", "说明": f"{'、'.join(others)}未评价；请检查数据及设计警告。"}
        )
    diagnostics.extend(_trend_transfer_diagnostics(data, result))
    assigned_result = result.get("指定值与不确定度", {})
    flagged = assigned_result.get("stability_flagged_periods", [])
    disposition = assigned_result.get("stability_disposition")
    blocked = disposition == "withhold" or (disposition == "pending" and bool(flagged))
    if blocked:
        names = "、".join(flagged) if flagged else "无"
        missing_periods = [
            name for name in flagged if name in periods and periods[name].get("conclusion") is None
        ]
        cause = (
            "上述判据问题导致稳定性未评价；"
            if standard == "gbt28043"
            and any(
                f"稳定性（{name}）" in explained or (missing and f"稳定性（{name}）" in sigma_items)
                for name in missing_periods
            )
            else ""
        )
        diagnostics.append(
            {
                "类型": "统计量暂停",
                "层级": "后果",
                "说明": f"{cause}稳定性处置为 {disposition}，未得出通过结论的时间组：{names}；"
                "请补充判据及数据，或由授权人员评定并登记 "
                "budgeted、reviewed 或 withhold 处置及依据。",
            }
        )
    if assigned_result and assigned_result.get("status") != "OK":
        warnings = "；".join(assigned_result.get("warnings", [])) or "请检查指定值及分量映射"
        diagnostics.append(
            {
                "类型": "指定值状态",
                "层级": "根因",
                "说明": f"指定值状态 {assigned_result.get('status')}：{warnings}。",
            }
        )
    if (
        data.get("participants")
        and not assigned_config.get("method")
        and cfg.get("assigned") not in (None, "")
        and sigma is None
        and cfg.get("sigma_pt") in (None, "")
        and not result.get("参加者z状态")
    ):
        diagnostics.append(
            {
                "类型": "参加者统计量未评价",
                "层级": "后果",
                "说明": "z 未评价：需要正的能力评定标准差 σ_pt。" + _sigma_advice(data),
            }
        )
    grouped_scores: dict[tuple[str, str], list[str]] = {}
    for participant, scores in result.get("参加者统计量", {}).items():
        for statistic, score in scores.items():
            if score.get("value") is None:
                reason = score.get("reason") or _unevaluated_reason(score, "原因未登记")
                if reason == "指定值或分量映射未通过审核":
                    other_warnings = [
                        w
                        for w in assigned_result.get("warnings", [])
                        if w != "稳定性或运输处置未完成，或已登记暂停评价"
                    ]
                    if blocked:
                        reason = f"稳定性处置为 {disposition}，参加者评价被暂停"
                        if other_warnings:
                            reason += "；" + "；".join(other_warnings)
                    elif other_warnings:
                        reason = "；".join(other_warnings)
                    else:
                        reason = f"指定值状态 {assigned_result.get('status')}，结果未提供具体原因"
                grouped_scores.setdefault((statistic, str(reason)), []).append(str(participant))
    for (statistic, reason), participants in grouped_scores.items():
        if "参加者 u(x)" in reason:
            advice = (
                "请在『参加者结果』填写标准不确定度u(x)，并在『指定值与不确定度』检查 uncertainty。"
            )
        elif "扩展不确定度" in reason and "包含因子" in reason:
            advice = (
                "请在『指定值与不确定度』填写 U_assigned、k_assigned，"
                "在『参加者结果』填写扩展不确定度U(x)、包含因子k。"
            )
        elif "能力评定标准差" in reason:
            advice = _sigma_advice(data)
        elif "未绑定唯一的传递标准校准点" in reason:
            advice = (
                "请在『方法配置』transfer_en_map 中将参加者编号绑定到"
                "『传递标准配置』的标准器|校准点。"
            )
        elif "缺少参考值扩展不确定度" in reason:
            advice = "请在『指定值与不确定度』填写 U_assigned 及 k_assigned。"
        elif "传递标准稳定性未通过或未评价" in reason:
            advice = "请检查『传递标准复测』的数据和『传递标准配置』的判据JSON，先完成稳定性审核。"
        elif "传递标准稳定性衔接条件" in reason:
            advice = (
                "请审核『传递标准配置』不确定度JSON 中的 mechanism、source "
                "及其机制参数，避免重复计入。"
            )
        elif "参考扩展不确定度已含稳定性" in reason:
            advice = (
                "请审核『传递标准配置』不确定度JSON 的 ref_includes_stability 和 U_E，"
                "避免重复计入。"
            )
        elif "使用 k=2" in reason:
            advice = (
                "请核实『指定值与不确定度』k_assigned 与『参加者结果』包含因子k，"
                "其他因子须采用批准模型。"
            )
        elif "不相关" in reason:
            advice = (
                "请由授权人员核实相关性，在『指定值与不确定度』登记 independent；"
                "不能确认时不得强行评价。"
            )
        elif "公议" in reason or "参与定值" in reason:
            advice = "请审核参加者与公议指定值的相关性，必要时使用经批准的评价模型。"
        elif "指定值标准不确定度" in reason:
            advice = "请在『指定值与不确定度』登记 uncertainty 及 uncertainty_source。"
        elif "指定值为零" in reason:
            advice = "请审核『指定值与不确定度』value 是否为零；零指定值不能计算百分相对差。"
        elif "分母为零" in reason:
            advice = (
                "请核实『指定值与不确定度』的标准差或不确定度，"
                "以及『参加者结果』中的不确定度，避免分母为零。"
            )
        elif "重复计入" in reason:
            advice = (
                "请审核『指定值与不确定度』的 hom_mapping、stab_mapping、trans_mapping "
                "及基础预算标识，消除重复计入。"
            )
        elif "未分配" in reason:
            advice = (
                "请审核『指定值与不确定度』的 u_trans、trans_mapping 和基础预算标识，登记运输分量。"
            )
        elif "稳定性处置" in reason:
            advice = "请先完成上列稳定性处置。"
        else:
            advice = "请依据该原因补充输入或由授权人员审核。"
        diagnostics.append(
            {
                "类型": "参加者统计量未评价",
                "层级": "后果",
                "说明": f"{statistic} 未评价：{reason}；参加者：{'、'.join(participants)}。"
                + advice,
            }
        )
    if diagnostics:
        result["诊断提示"] = diagnostics
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
            # 定位豁免：命令行路径不属于工作簿表格。
            raise InputError(f"{name} 路径不能为空")
        if not Path(value).exists():
            # 定位豁免：命令行路径不属于工作簿表格。
            raise InputError(f"{name} 路径不存在：{value}")
    output_names = ["output", "docx", "json", "differences", "runs_dir"]
    if args.command == "demo":
        output_names.append("directory")
    for name in output_names:
        value = getattr(args, name, None)
        if value is not None and (not value or not str(value).strip()):
            # 定位豁免：命令行输出路径不属于工作簿表格。
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
        for item in result.get("诊断提示", []):
            print(f"诊断提示：{item['说明']}")
        for name, part in result.get("被测量", {}).items():
            for item in part.get("诊断提示", []):
                print(f"诊断提示（{name}）：{item['说明']}")
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
        print(f"错误：{format_error(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
