# SPDX-License-Identifier: Apache-2.0
"""声称值与模型对照；严格显示位数和末位容差分开。"""

import csv
import math
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from ..config.catalog import ENUMS, HOMOGENEITY_CLAIM_NAMES
from ..config.sigma import criterion_sigma
from ..core.decision import compare
from ..core.gbt28043 import criterion_limit as gbt_criterion_limit
from ..core.gbt28043 import homogeneity as gbt_homogeneity
from ..core.gbt28043 import period_options as gbt_period_options
from ..core.gbt28043 import stability as gbt_stability
from ..core.robust import algorithm_a
from ..core.stability import analyze as stability
from ..core.stability import summary_t


def display(value: float | Decimal | None, digits: int) -> Decimal | None:
    """按报告显示位数进行十进制四舍五入。"""
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def _period(result: dict[str, Any], name: Any) -> tuple[str, dict[str, Any]]:
    """按实际主时间组名称查找稳定性结果。"""
    primary = result.get("稳定性时间组") or "稳定期"
    selected = name or primary
    value = (
        result.get("稳定性", {})
        if selected == primary
        else result.get("其他稳定性", {}).get(selected, {})
    )
    return str(selected), value


def _t_reproduction(
    data: dict[str, Any], result: dict[str, Any], claim: dict[str, Any]
) -> tuple[Any, Any, str]:
    """按 GL003 5.2.2 对指定时点计算报告和推荐模型。"""
    cfg = data["config"]
    groups = data["stability"]
    name, selected = _period(result, claim.get("timegroup"))
    model = claim.get("model") or (
        "repeats_pooled" if cfg.get("observation_level") == "all_repeats" else "recommended"
    )
    recommended = selected.get("t")
    if selected.get("status") == "DESIGN_REVIEW":
        return None, None, "实验设计需审核，不计算候选模型"
    if model in ("repeats_pooled", "repeats_welch"):
        reference = cfg.get("reference")
        report_result = stability(
            groups.get("基线"),
            groups[name],
            model=model,
            method=cfg.get("stability_method") or "two_sample",
            reference=float(reference) if reference not in (None, "") else None,
        )
        detail = (
            f"技术重复仅用于报告模型复现，须核查伪重复及自由度；报告模型 df={report_result['df']}，"
            f"推荐模型 df={selected.get('df')}；模型={model}"
        )
        return report_result["t"], recommended, detail
    if model == "displayed_summary":
        keys = ("mean1", "mean2", "s1", "s2", "n1", "n2")
        if all(cfg.get(k) not in (None, "") for k in keys):
            reproduced = summary_t(
                float(cfg["mean1"]),
                float(cfg["mean2"]),
                float(cfg["s1"]),
                float(cfg["s2"]),
                int(cfg["n1"]),
                int(cfg["n2"]),
            )["t"]
            return (
                reproduced,
                recommended,
                (f"按报告修约中间值重算；报告 s1={cfg['s1']}，推荐模型 s1={selected.get('s1')}"),
            )
        return None, recommended, "报告显示汇总量不完整"
    note = (
        "t 值仅供参考，不作为 GL003 5.3 均值差结论"
        if selected.get("method") == "mean_difference"
        else ""
    )
    return (recommended if model == "recommended" else None), recommended, note


def _standard_value(
    data: dict[str, Any], result: dict[str, Any], claim: dict[str, Any], mode: str
) -> Any:
    """按选定模式重算可比中间量；标准未提供的扩展限值返回空。"""
    cfg = data.get("config", {})
    name = claim["name"]
    group, s = _period(result, claim.get("timegroup"))
    if mode == "gl003":
        h = result.get("均匀性", {})
        return {
            "Ss": h.get("Ss"),
            "均匀性基本限值": h.get("threshold"),
            "稳定性均值差": s.get("difference"),
            "稳定性基本限值": s.get("threshold"),
        }.get(name)
    sigma = criterion_sigma(cfg)
    delta_e = cfg.get("delta_e") if cfg.get("delta_e") not in (None, "") else None
    basis = cfg.get("gbt_criterion_basis") or None
    if name in ("Ss", "均匀性基本限值", "均匀性扩展限值") and data.get("homogeneity"):
        h = result.get("GB/T均匀性")
        if not h and cfg.get("replicate_type") == "single":
            _, limit = gbt_criterion_limit(sigma, delta_e, basis)
            h = {
                "ss": result.get("均匀性", {}).get("Ss"),
                "basic_limit": limit,
                "extended_limit": None,
            }
        if not h:
            h = gbt_homogeneity(data["homogeneity"], sigma, delta_e=delta_e, basis=basis)
        return h[
            {"Ss": "ss", "均匀性基本限值": "basic_limit", "均匀性扩展限值": "extended_limit"}[name]
        ]
    groups = data.get("stability", {})
    gbt_period = result.get("GB/T稳定性", {}).get(group)
    if gbt_period and name in ("稳定性均值差", "稳定性基本限值", "稳定性扩展限值"):
        return gbt_period[
            {
                "稳定性均值差": "difference",
                "稳定性基本限值": "basic_limit",
                "稳定性扩展限值": "extended_limit",
            }[name]
        ]
    source = cfg.get("baseline_source") or (
        "homogeneity" if cfg.get("stability_method") == "mean_difference" else "baseline_group"
    )
    baseline = data.get("homogeneity") if source == "homogeneity" else groups.get("基线")
    if (
        name in ("稳定性均值差", "稳定性基本限值", "稳定性扩展限值")
        and baseline
        and group in groups
    ):
        settings = gbt_period_options(cfg, groups)
        s = gbt_stability(
            baseline,
            groups[group],
            sigma,
            delta_e=delta_e,
            basis=basis,
            independent=(cfg.get("stability_design") or "independent") == "independent",
            allow_single_baseline=source == "homogeneity" and cfg.get("replicate_type") == "single",
            **settings[group],
        )
        return s[
            {
                "稳定性均值差": "difference",
                "稳定性基本限值": "basic_limit",
                "稳定性扩展限值": "extended_limit",
            }[name]
        ]
    return None


def _values(
    data: dict[str, Any], result: dict[str, Any], claim: dict[str, Any]
) -> tuple[Any, Any, str]:
    name = claim["name"]
    cfg = data["config"]
    aliases = {
        "均值差": "稳定性均值差",
        "|x̄-ȳ|": "稳定性均值差",
        "F值": "F",
        "方差分析F值": "F",
    }
    if name in ("0.3σ", "0.3σ阈值", "0.3σ 阈值"):
        sigma_for_threshold = criterion_sigma(cfg)
        threshold = 0.3 * sigma_for_threshold if sigma_for_threshold is not None else None
        return threshold, threshold, ""
    canonical = aliases.get(name, name)
    _, period = _period(result, claim.get("timegroup"))
    if name in ("x̄", "xbar", "均匀性总平均值"):
        value = result.get("均匀性", {}).get("mean")
        return value, value, ""
    if name in ("ȳ", "ȳ", "ybar", "稳定性时间组平均值"):
        value = period.get("mean2")
        return value, value, ""
    if canonical != name:
        return _values(data, result, {**claim, "name": canonical})
    standard_names = (
        "Ss",
        "均匀性基本限值",
        "均匀性扩展限值",
        "稳定性均值差",
        "稳定性基本限值",
        "稳定性扩展限值",
    )
    model = claim.get("model")
    if name in standard_names and (
        model in ("gl003", "gbt28043") or name != "Ss" or cfg.get("report_standard")
    ):
        selected = cfg.get("criterion_standard") or "gl003"
        report_mode = (
            model if model in ("gl003", "gbt28043") else cfg.get("report_standard") or selected
        )
        try:
            report_value = _standard_value(data, result, claim, report_mode)
            recommended_value = _standard_value(data, result, claim, selected)
        except ValueError:
            return None, None, "标准模式所需数据或实验设计不适用"
        note = (
            f"报告标准模式={report_mode}；推荐模式={selected}"
            if report_mode != selected
            or cfg.get("report_standard")
            or model in ("gl003", "gbt28043")
            else ""
        )
        if selected == "gbt28043" and name.endswith("限值"):
            rule_key = "gbt_hom_rule" if name.startswith("均匀性") else "gbt_stability_rule"
            primary = cfg.get(rule_key) or "basic"
            requested = "extended" if "扩展" in name else "basic"
            note += f"；预选主判据={primary}"
            if requested != primary:
                recommended_value = None
                note += "；此限值非预选主判据，仅供参考"
        return report_value, recommended_value, note
    if name in ("F", "Ss"):
        value = result.get("均匀性", {}).get(name)
        return value, value, ""
    if name == "NIQR":
        value = result.get("中位数NIQR", {}).get("niqr")
        return value, value, ""
    if name == "u(X)":
        value = result.get("指定值与不确定度", {}).get("u")
        return value, value, ""
    if ":" in name:
        kind, participant_id = name.split(":", 1)
        kind = {"z′": "zprime", "z'": "zprime", "ζ": "zeta"}.get(kind, kind)
        score = result.get("参加者统计量", {}).get(participant_id, {}).get(kind, {})
        if score:
            value = score.get("value") if score.get("status") == "OK" else None
            return value, value, score.get("reason") or ""
    if name in ("x*", "s*"):
        key = "x" if name == "x*" else "s"
        value = result.get("算法A", {}).get(key)
        if claim.get("model") in ("absolute", "gbt28043") and data.get("participants"):
            rule = claim["model"]
            alternative = algorithm_a([p["value"] for p in data["participants"]], rule=rule)
            if not alternative.converged:
                note = (
                    "绝对容差模型未收敛，未评价；报告停止规则待底稿确认"
                    if rule == "absolute"
                    else "GB/T 28043 C.3.1 报告模型未收敛，未评价"
                )
                return None, value, note
            note = (
                "绝对容差作为候选报告模型，原报告停止规则待底稿确认"
                if rule == "absolute"
                else "报告使用 GB/T 28043 C.3.1 各自三位有效数字停止规则"
            )
            return alternative[key], value, note
        return value, value, ""
    if name == "t":
        return _t_reproduction(data, result, claim)
    if name.startswith("z:"):
        participant = next((p for p in data["participants"] if p["id"] == name[2:]), None)
        sigma_value = cfg.get("sigma_pt") or cfg.get("sigma")
        if participant and cfg.get("assigned") not in (None, "") and sigma_value not in (None, ""):
            sigma = Decimal(str(sigma_value))
            if sigma <= 0:
                raise ValueError("能力评价标准差必须大于零")
            value = (Decimal(str(participant["value"])) - Decimal(str(cfg["assigned"]))) / sigma
            if result.get("参加者z状态"):
                return value, None, "仅复现报告数值；稳定性处置未完成，推荐评价暂停"
            return value, value, ""
    return None, None, ""


def _row(
    name: str,
    claim: float,
    digits: int,
    source: str,
    model_value: Any,
    recommended: Any,
    note: str,
    categories: list[str],
    item: str,
    *,
    informational_note: bool = False,
) -> dict[str, Any]:
    try:
        if not 0 <= digits <= 12:
            raise ValueError("显示位数超出范围")
        shown_claim = display(claim, digits)
        shown_model = display(model_value, digits)
        shown_recommended = display(recommended, digits)
        match = shown_model == shown_claim if model_value is not None else None
        recommended_match = shown_recommended == shown_claim if recommended is not None else None
    except (ValueError, TypeError, InvalidOperation):
        raise ValueError("报告数值或显示小数位无效") from None
    # 对只有一个可计算模型的量，显示不一致才构成数值差异；多模型量在调用处判定。
    if match is False and name not in ("t", "x*", "s*"):
        categories.append("VALUE_MISMATCH")
        if name.startswith("z:"):
            note = (
                note + f"；按显示位数重算为 {shown_model}，报告为 {shown_claim}；原因待底稿确认"
            ).lstrip("；")
        else:
            note = (note + "；原因待底稿确认").lstrip("；")
    if match is None:
        note = (note + "；未评价：缺少输入或所选模型无法计算").lstrip("；")
    status = (
        "DIFFERENCE"
        if "VALUE_MISMATCH" in categories
        else (
            "NOTE"
            if match is not True
            or recommended_match is False
            or categories
            or (note and not informational_note)
            else "MATCH"
        )
    )
    return {
        "统计量": name,
        "声称值": claim,
        "来源": source,
        "显示小数位": digits,
        "按报告模型复现值": float(model_value) if isinstance(model_value, Decimal) else model_value,
        "按推荐模型重算值": float(recommended) if isinstance(recommended, Decimal) else recommended,
        "按报告显示值": str(shown_model) if shown_model is not None else None,
        "按推荐显示值": str(shown_recommended) if shown_recommended is not None else None,
        "显示一致": match,
        "推荐一致": recommended_match,
        "状态": status,
        "差异类型": "|".join(dict.fromkeys(categories)),
        "评分条目": item,
        "说明": note,
    }


def _candidate_models(
    data: dict[str, Any], result: dict[str, Any], claim: dict[str, Any], digits: int
) -> tuple[bool | None, tuple[str, Any] | None]:
    """判断可复现性，并返回可计算候选中最接近声称值的模型。"""
    group, _ = _period(result, claim.get("timegroup"))
    try:
        candidates = [
            (
                label,
                stability(data["stability"].get("基线"), data["stability"][group], model=m)["t"],
            )
            for m, label in (
                ("unit_pooled", "单元均值"),
                ("repeats_pooled", "重复值合并方差"),
                ("repeats_welch", "重复值非齐方差"),
            )
        ]
        if group == (result.get("稳定性时间组") or "稳定期"):
            summary, _, _ = _t_reproduction(data, result, {**claim, "model": "displayed_summary"})
            if summary is not None:
                candidates.append(("修约中间值", summary))
        valid = [(label, value) for label, value in candidates if value is not None]
        target = Decimal(str(claim["value"]))
        closest = min(valid, key=lambda item: abs(Decimal(str(item[1])) - target), default=None)
        if any(display(value, digits) == display(target, digits) for _, value in valid):
            return False, closest
        return (True if len(valid) == len(candidates) else None), closest
    except (ValueError, KeyError, InvalidOperation):
        return None, None


def _algorithm_candidates(
    data: dict[str, Any], name: str, claim: float, digits: int
) -> bool | None:
    """检查算法 A 的候选停止规则；数据不足时不推断无法复现。"""
    try:
        values = [p["value"] for p in data["participants"]]
        results = [
            algorithm_a(values, rule=rule)
            for rule in ("gl002", "gbt28043", "absolute", "simplified")
        ]
        valid = [r[name] for r in results if r.converged and r.status == "OK"]
        if any(display(value, digits) == display(claim, digits) for value in valid):
            return False
        return True if len(valid) == len(results) else None
    except (ValueError, KeyError):
        return None


def _adjudicate_models(
    data: dict[str, Any],
    result: dict[str, Any],
    claim: dict[str, Any],
    row: dict[str, Any],
    digits: int,
) -> None:
    """区分候选模型差异与所有候选均无法复现的数值差异。"""
    name = claim["name"]
    if name == "t" and row["显示一致"] is False:
        candidate, closest = _candidate_models(data, result, claim, digits)
        if closest is not None:
            label, value = closest
            gap = abs(Decimal(str(value)) - Decimal(str(claim["value"])))
            unit = Decimal(1).scaleb(-digits)
            if gap < unit:
                row["说明"] += (
                    f"；最接近的候选模型（{label}）{display(value, digits + 1)} "
                    f"与声称值 {display(claim['value'], digits)} 相差 {display(gap, digits + 1)}，"
                    f"不足一个显示单位（{unit}），但严格修约不一致"
                )
        if candidate is True:
            row["差异类型"] = "|".join(
                filter(None, (row["差异类型"], "VALUE_MISMATCH", "NOT_REPRODUCIBLE"))
            )
            row["状态"] = "DIFFERENCE"
        elif candidate is False:
            row["说明"] += "；其他候选模型可按显示位数复现"
        else:
            row["说明"] += "；候选模型数据不足，未能确认数值差异"
    if name in ("x*", "s*"):
        _adjudicate_stop_rules(data, claim, row, digits)


def _adjudicate_stop_rules(
    data: dict[str, Any],
    claim: dict[str, Any],
    row: dict[str, Any],
    digits: int,
) -> None:
    """把算法 A 停止规则敏感性与报告数值错误分开。"""
    if row["显示一致"] is True and row["推荐一致"] is False:
        row["差异类型"] = "|".join(filter(None, (row["差异类型"], "STOP_RULE_SENSITIVITY")))
        row["状态"] = "NOTE"
        row["说明"] += "；停止规则敏感，不据此认定报告错误"
    elif row["显示一致"] is False:
        key = "x" if claim["name"] == "x*" else "s"
        candidates = _algorithm_candidates(data, key, claim["value"], digits)
        if candidates is True:
            row["差异类型"] = "|".join(
                filter(None, (row["差异类型"], "VALUE_MISMATCH", "NOT_REPRODUCIBLE"))
            )
            row["状态"] = "DIFFERENCE"
            row["说明"] += "；全部可选停止规则均不一致，原因待底稿确认"
        elif candidates is False:
            row["差异类型"] = "|".join(filter(None, (row["差异类型"], "STOP_RULE_SENSITIVITY")))
            row["说明"] += "；其他停止规则可复现，不据此认定报告错误"
        else:
            row["说明"] += "；候选停止规则无法完整计算，未能确认数值差异"


def _mapping_item(mapping: dict[str, Any], name: str, group: str) -> str:
    """按统计量优先取评分条目；单项可映射至多个条目。"""
    default = "均匀性与稳定性评估" if group == "homogeneity" else "能力统计量计算"
    value = mapping.get(name, mapping.get(name.split(":", 1)[0], mapping.get(group, default)))
    if isinstance(value, list):
        if not all(isinstance(item, str) for item in value):
            raise ValueError("评分映射列表必须为字符串")
        return "；".join(value)
    if not isinstance(value, str):
        raise ValueError("评分映射必须为字符串或字符串列表")
    return value


def _reported_mean_difference(
    data: dict[str, Any], result: dict[str, Any], claim: dict[str, Any]
) -> tuple[float, str] | None:
    """仅在显式登记报告均值时复现报告算术，不把报告基线当成推荐基线。"""
    if data.get("config", {}).get("stability_method") != "mean_difference":
        return None
    if claim.get("name") not in ("均值差", "稳定性均值差", "|x̄-ȳ|"):
        return None
    if claim.get("model") not in (None, "", "recommended", "gl003", "gbt28043"):
        return None
    group, period = _period(result, claim.get("timegroup"))
    if period.get("status") == "DESIGN_REVIEW" or period.get("mean2") is None:
        return None
    primary = result.get("稳定性时间组") or "稳定期"
    claims = data.get("claims", [])
    x_names = ("x̄", "xbar", "均匀性总平均值")
    y_names = ("ȳ", "ȳ", "ybar", "稳定性时间组平均值")
    matching_x = [
        item for item in claims if item.get("name") in x_names and item.get("timegroup") == group
    ]
    if not matching_x:
        matching_x = [
            item for item in claims if item.get("name") in x_names and not item.get("timegroup")
        ]
    matching_y = [
        item
        for item in claims
        if item.get("name") in y_names and (item.get("timegroup") or primary) == group
    ]
    x_values = {float(item["value"]) for item in matching_x}
    y_values = {float(item["value"]) for item in matching_y}
    if len(x_values) != 1 or len(y_values) > 1:
        return None
    x = next(iter(x_values))
    y = next(iter(y_values)) if y_values else float(period["mean2"])
    return abs(x - y), f"按报告声明的 x̄={x}、ȳ={y} 复现算术；推荐模型使用配置的正确基线"


def _review_claim(
    data: dict[str, Any],
    result: dict[str, Any],
    claim: dict[str, Any],
    models: set[Any],
    mapping: dict[str, Any],
) -> list[dict[str, Any]]:
    """复核一条声称值并产生必要的附加中间量差异。"""
    name = claim["name"]
    model = claim.get("model") or (
        "repeats_pooled"
        if claim["name"] == "t" and data["config"].get("observation_level") == "all_repeats"
        else "recommended"
    )
    try:
        digits = int(claim["digits"])
        if isinstance(claim["digits"], bool) or float(claim["digits"]) != digits:
            raise ValueError("显示位数必须为整数")
    except (ValueError, TypeError, OverflowError):
        raise ValueError("报告声称值显示小数位须为0至12的整数") from None
    reproduced, rec, note = _values(data, result, claim)
    report_means = _reported_mean_difference(data, result, claim)
    if report_means is not None:
        reproduced, report_note = report_means
        note = (note + "；" + report_note).strip("；")
    if name in ("x̄", "xbar", "均匀性总平均值") and rec is not None:
        _, period = _period(result, claim.get("timegroup"))
        if display(claim["value"], digits) != display(rec, digits):
            mean, threshold = period.get("mean2"), period.get("threshold")
            note = f"报告 x̄={claim['value']}；均匀性总平均值={rec}"
            if mean is not None and threshold is not None:
                stated_pass = compare(abs(claim["value"] - mean), threshold) <= 0
                correct_pass = compare(abs(rec - mean), threshold) <= 0
                note += "；结论不受影响" if stated_pass == correct_pass else "；结论受影响"
            else:
                note += "；结论影响未评价"
    types = []
    if name in ("x*", "s*") and model == "absolute":
        types.append("REPORT_RULE_UNKNOWN")
    if name == "Ss":
        cfg = data["config"]
        gbt = result.get("GB/T均匀性") if cfg.get("criterion_standard") == "gbt28043" else None
        if gbt is not None:
            failed = gbt.get("conclusion") is False
            limit = gbt.get(f"{gbt.get('selected_rule')}_limit")
            label = "GB/T 预选主判据限值"
        else:
            failed = result.get("均匀性", {}).get("Ss_pass") is False
            limit = result.get("均匀性", {}).get("threshold")
            label = "0.3σ"
        if failed:
            note = f"样品间标准差超过 {label}：{rec} > {limit}"
            if cfg.get("sigma_composite") not in (None, ""):
                note += "；报告处置：将样品间标准差合成为 σ′"
            else:
                note += "；报告处置方式未提供"
            types.append("CRITERION_EXCEEDED")
    if model.startswith("repeats"):
        types.append("PSEUDO_REPLICATION")
    if model == "repeats_welch" and "repeats_pooled" in models:
        types.append("MODEL_SWITCH")
    if model == "displayed_summary":
        types.append("ROUNDING_INTERMEDIATE")
    item = _mapping_item(
        mapping, name, "homogeneity" if name in HOMOGENEITY_CLAIM_NAMES else "performance"
    )
    source = claim["source"]
    if claim.get("cell"):
        source = f"{source}；输入单元格：{claim['cell']}"
    selected_standard = data["config"].get("criterion_standard") or "gl003"
    mode_information = note == f"报告标准模式={selected_standard}；推荐模式={selected_standard}"
    row = _row(
        name,
        claim["value"],
        digits,
        source,
        reproduced,
        rec,
        note,
        types,
        item,
        informational_note=mode_information,
    )
    if report_means is not None and row["显示一致"] is True and not row["差异类型"]:
        row["状态"] = "MATCH"
        if row["推荐一致"] is False:
            row["说明"] += "；按推荐基线的数值不同，须结合均值差异条目复核"
    _adjudicate_models(data, result, claim, row, digits)
    rows = [row]
    if report_means is not None and row["显示一致"] is True and row["推荐一致"] is False:
        rows.append(
            {
                **row,
                "统计量": name + "（推荐基线）",
                "状态": "NOTE",
                "差异类型": "MODEL_SWITCH",
                "说明": row["说明"] + "；报告数值仅与所声明均值的算术一致，不能代替推荐基线判定",
            }
        )
    if name == "t" and model == "displayed_summary" and data["config"].get("s1") is not None:
        s1 = result.get("稳定性", {}).get("s1")
        stated = float(data["config"]["s1"])
        if s1 is not None and display(stated, 3) != display(s1, 3):
            rows.append(
                _row(
                    "s1",
                    stated,
                    3,
                    claim["source"],
                    s1,
                    s1,
                    "基线标准差不符，原因待底稿确认",
                    [],
                    item,
                )
            )
    return rows


def _composite_row(
    data: dict[str, Any], result: dict[str, Any], mapping: dict[str, Any]
) -> dict[str, Any] | None:
    """核查声称的标准差合成及其稳定性用途。"""
    cfg = data["config"]
    sigma = criterion_sigma(cfg)
    if cfg.get("sigma_composite") in (None, "") or sigma is None:
        return None
    ss = cfg.get("sigma_ss")
    if ss in (None, ""):
        ss = result.get("均匀性", {}).get("Ss")
    composite = math.hypot(sigma, float(ss)) if ss is not None else None
    reported_sigma = cfg.get("reported_stability_sigma")
    if reported_sigma == cfg["sigma_composite"]:
        source_note = "稳定性报告使用合成标准差"
    elif reported_sigma == sigma:
        source_note = "稳定性报告使用原标准差"
    else:
        source_note = "稳定性所用标准差待确认"
    return _row(
        "合成标准差",
        float(cfg["sigma_composite"]),
        int(cfg.get("sigma_composite_digits") or 1),
        str(cfg.get("sigma_source") or "输入配置"),
        composite,
        composite,
        ("缺少样品间标准差，未评价；" if composite is None else "合成标准差用途需确认；")
        + source_note,
        ["SIGMA_COMPOSITE"],
        _mapping_item(mapping, "合成标准差", "homogeneity"),
    )


def _design_rows(
    result: dict[str, Any], mapping: dict[str, Any], *, suppress_t_sample_warning: bool = False
) -> list[dict[str, Any]]:
    """将稳定性抽样设计提示单独列入复核清单。"""
    periods = []
    if result.get("稳定性"):
        periods.append((result.get("稳定性时间组") or "稳定期", result["稳定性"]))
    periods.extend(result.get("其他稳定性", {}).items())
    rows = []
    for name, values in periods:
        warnings = values.get("design_warnings", [])
        if suppress_t_sample_warning:
            warnings = [warning for warning in warnings if "GL003 5.2." not in warning]
        if not warnings:
            continue
        rows.append(
            {
                "统计量": f"{name}设计",
                "声称值": None,
                "来源": "稳定性工作表",
                "显示小数位": None,
                "按报告模型复现值": None,
                "按推荐模型重算值": None,
                "显示一致": None,
                "推荐一致": None,
                "状态": "NOTE",
                "差异类型": "DESIGN_WARNING",
                "评分条目": _mapping_item(mapping, f"{name}设计", "homogeneity"),
                "说明": "；".join(warnings),
            }
        )
    return rows


def _applicable_standard(name: str, note: str, selected: str) -> str:
    """按统计量和复核模式标注标准；跨标准比较明确标出两者。"""
    if name in ("F", "F值", "方差分析F值", "t", "s1", "稳定性方法", "GL003均匀性主判据") or (
        name.endswith("设计") and name != "重复性质设计"
    ):
        return "GL003"
    base = name.removesuffix("（推荐基线）")
    if base in HOMOGENEITY_CLAIM_NAMES:
        if (
            "报告标准模式=gl003；推荐模式=gbt28043" in note
            or "报告标准模式=gbt28043；推荐模式=gl003" in note
        ):
            return "GL003/GB/T"
        return "GB/T" if selected == "gbt28043" else "GL003"
    return "通用"


def review(
    data: dict[str, Any], result: dict[str, Any], mapping: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """比较 GL002 和 GL003 计算结果、报告模型和声称值。"""
    if data.get("measurands"):
        rows = []
        for name, part in data["measurands"].items():
            for row in review(part, result["被测量"][name], mapping):
                rows.append({"被测量": name, **row})
        return rows
    mapping = mapping or {"homogeneity": "均匀性与稳定性评估", "performance": "能力统计量计算"}
    models = {c.get("model") for c in data["claims"] if c.get("name") == "t"}
    rows = []
    cfg = data.get("config", {})
    report_standard = cfg.get("report_standard")
    selected = cfg.get("criterion_standard") or "gl003"
    if report_standard not in (None, "") and report_standard not in ENUMS["report_standard"]:
        raise ValueError("report_standard 应为 gl003 或 gbt28043")
    if report_standard and report_standard != selected:
        rows.append(
            {
                "统计量": "标准模式",
                "声称值": report_standard,
                "来源": "方法配置",
                "显示小数位": None,
                "按报告模型复现值": report_standard,
                "按推荐模型重算值": selected,
                "按报告显示值": report_standard,
                "按推荐显示值": selected,
                "显示一致": True,
                "推荐一致": False,
                "状态": "NOTE",
                "差异类型": "STANDARD_MODE",
                "评分条目": _mapping_item(mapping, "标准模式", "homogeneity"),
                "说明": "报告模式与推荐模式不同；差异不自动认定为报告错误。",
            }
        )
    report_criterion = cfg.get("report_gl003_hom_criterion")
    if (
        report_criterion not in (None, "")
        and report_criterion not in ENUMS["report_gl003_hom_criterion"]
    ):
        raise ValueError("report_gl003_hom_criterion 无效")
    selected_criterion = (
        "both" if cfg.get("strict_homogeneity") else (cfg.get("gl003_hom_criterion") or "f_test")
    )
    if selected == "gl003" and report_criterion and report_criterion != selected_criterion:
        rows.append(
            {
                "统计量": "GL003均匀性主判据",
                "声称值": report_criterion,
                "来源": "方法配置",
                "显示小数位": None,
                "按报告模型复现值": report_criterion,
                "按推荐模型重算值": selected_criterion,
                "按报告显示值": report_criterion,
                "按推荐显示值": selected_criterion,
                "显示一致": True,
                "推荐一致": False,
                "状态": "NOTE",
                "差异类型": "MODEL_SWITCH",
                "评分条目": _mapping_item(mapping, "GL003均匀性主判据", "homogeneity"),
                "说明": "报告声明的均匀性判据与配置不同；须核对报告口径。",
            }
        )
    report_method = cfg.get("report_stability_method")
    selected_method = cfg.get("stability_method") or "two_sample"
    if report_method not in (None, "") and report_method not in ENUMS["report_stability_method"]:
        raise ValueError("report_stability_method 无效")
    if report_method and report_method != selected_method:
        rows.append(
            {
                "统计量": "稳定性方法",
                "声称值": report_method,
                "来源": "方法配置",
                "显示小数位": None,
                "按报告模型复现值": report_method,
                "按推荐模型重算值": selected_method,
                "显示一致": True,
                "推荐一致": False,
                "状态": "NOTE",
                "差异类型": "MODEL_SWITCH",
                "评分条目": _mapping_item(mapping, "稳定性方法", "homogeneity"),
                "说明": "报告声明的方法与配置不同，须按报告实际方法重新配置并复核。",
            }
        )
    if cfg.get("replicate_type") == "adjacent_specimens" and data.get("homogeneity"):
        rows.append(
            {
                "统计量": "重复性质设计",
                "声称值": None,
                "来源": "方法配置",
                "显示小数位": None,
                "按报告模型复现值": None,
                "按推荐模型重算值": None,
                "显示一致": None,
                "推荐一致": None,
                "状态": "NOTE",
                "差异类型": "DESIGN_WARNING|DESTRUCTIVE_ADJACENT",
                "评分条目": _mapping_item(mapping, "重复性质设计", "homogeneity"),
                "说明": "扩展提示：组内方差包含相邻试件之间的差异，可能低估样品间不均匀性。",
            }
        )
    trend_names = {
        "b1": "b1",
        "b0": "b0",
        "s(b1)": "s(b1)",
        "趋势阈值": "阈值",
        "趋势X̄": "X̄",
        "趋势Ȳ": "Ȳ",
        "趋势t临界值": "t",
        "趋势结论": "结论",
    }
    trend_claims: dict[str, list[dict[str, Any]]] = {}
    trend_results = result.get("趋势稳定性", {})
    transfer_results = result.get("传递标准稳定性", {})
    transfer_names = {
        "Δmax": "Δmax",
        "传递限值": "限值",
        "U_E": "U_E",
        "u_stab": "u_stab",
        "传递结论": "结论",
    }
    if cfg.get("replicate_type") == "single" and data.get("homogeneity"):
        rows.append(
            {
                "统计量": "重复性质设计",
                "声称值": None,
                "来源": "方法配置",
                "显示小数位": None,
                "按报告模型复现值": None,
                "按推荐模型重算值": None,
                "按报告显示值": None,
                "按推荐显示值": None,
                "显示一致": None,
                "推荐一致": None,
                "状态": "NOTE",
                "差异类型": "DESIGN_WARNING",
                "评分条目": _mapping_item(mapping, "重复性质设计", "homogeneity"),
                "说明": "GB/T 28043-2019 B.1.2：单次测量标准差含测量误差，"
                "结论偏保守，须选择重复性足够低的方法。",
            }
        )
    for claim in data["claims"]:
        if claim["name"] in transfer_names and transfer_results:
            from .transfer import review_transfer

            group = claim.get("timegroup") or (
                next(iter(transfer_results)) if len(transfer_results) == 1 else None
            )
            if group not in transfer_results:
                raise ValueError("传递标准声称值须指定标准器|校准点")
            value = claim["value"]
            if claim["name"] == "传递结论":
                if value not in (0, 1):
                    raise ValueError("传递结论须为1（稳定）或0（不稳定）")
                value = "稳定" if value == 1 else "不稳定"
            request = {
                "name": transfer_names[claim["name"]],
                "value": value,
                "digits": claim.get("digits"),
            }
            model = claim.get("model") or ""
            if isinstance(model, str) and model.startswith("rule:"):
                try:
                    request["rule_index"] = int(model[5:]) - 1
                except ValueError:
                    raise ValueError("传递判据序号应为 rule:1 等正整数") from None
            item = review_transfer(transfer_results[group], request)
            actual = item.get("重算值")
            rows.append(
                {
                    "统计量": item["统计量"],
                    "时间组": str(group),
                    "声称值": value,
                    "来源": claim.get("source", ""),
                    "显示小数位": claim.get("digits"),
                    "按报告模型复现值": actual,
                    "按推荐模型重算值": actual,
                    "按报告显示值": str(actual) if actual is not None else None,
                    "按推荐显示值": str(actual) if actual is not None else None,
                    "显示一致": item.get("显示一致"),
                    "推荐一致": item.get("显示一致"),
                    "状态": item["状态"],
                    "差异类型": item["差异类型"],
                    "评分条目": _mapping_item(mapping, item["统计量"], "homogeneity"),
                    "说明": item["说明"],
                }
            )
            continue
        if claim["name"] not in trend_names or not trend_results:
            rows.extend(_review_claim(data, result, claim, models, mapping))
            continue
        name = claim.get("timegroup") or (
            next(iter(trend_results)) if len(trend_results) == 1 else None
        )
        if name not in trend_results:
            raise ValueError("趋势声称值须指定存在的序列名")
        value = claim["value"]
        if claim["name"] == "趋势结论":
            if value not in (0, 1):
                raise ValueError("趋势结论声称值须为1（稳定）或0（趋势显著）")
            value = "稳定" if value == 1 else "趋势显著"
        digits = claim.get("digits")
        if isinstance(digits, float) and digits.is_integer():
            digits = int(digits)
        trend_claims.setdefault(str(name), []).append(
            {
                "name": trend_names[claim["name"]],
                "value": value,
                "digits": digits,
                "source": claim.get("source", ""),
                "cell": claim.get("cell", ""),
            }
        )
    if trend_claims:
        from .trend import review_trend

        for group, claims in trend_claims.items():
            for item in review_trend(trend_results[group], claims):
                corresponding = next(
                    (claim for claim in claims if claim["name"] == item["统计量"]), {}
                )
                value, actual = item.get("声称值"), item.get("重算值")
                rows.append(
                    {
                        "统计量": item["统计量"],
                        "时间组": group,
                        "声称值": value,
                        "来源": corresponding.get("source", ""),
                        "显示小数位": corresponding.get("digits"),
                        "按报告模型复现值": actual,
                        "按推荐模型重算值": actual,
                        "按报告显示值": str(actual) if actual is not None else None,
                        "按推荐显示值": str(actual) if actual is not None else None,
                        "显示一致": item.get("显示一致"),
                        "推荐一致": item.get("显示一致"),
                        "状态": item["状态"],
                        "差异类型": item["差异类型"],
                        "评分条目": _mapping_item(mapping, item["统计量"], "homogeneity"),
                        "说明": item["说明"],
                    }
                )
    composite = _composite_row(data, result, mapping)
    if composite is not None:
        rows.append(composite)
    rows.extend(
        _design_rows(
            result,
            mapping,
            suppress_t_sample_warning=report_method == "mean_difference"
            and selected_method != "mean_difference",
        )
    )
    for row in rows:
        row["适用标准"] = _applicable_standard(
            str(row.get("统计量", "")), str(row.get("说明", "")), selected
        )
        if row["状态"] in ("NOTE", "DIFFERENCE") and not row["差异类型"]:
            row["差异类型"] = "REVIEW_NOTE" if row["状态"] == "NOTE" else "REVIEW_REQUIRED"
        name = row.get("统计量", "")
        participant_id = name.split(":", 1)[1] if ":" in name else None
        participant = next(
            (p for p in data.get("participants", []) if p["id"] == participant_id), None
        )
        if participant:
            locations = [participant.get("source", "")]
        elif name in ("x*", "s*", "NIQR", "u(X)"):
            locations = [p.get("source", "") for p in data.get("participants", [])]
        else:
            locations = data.get("sources", [])
        row["计算数据来源"] = "、".join(location for location in locations if location)
    priority = {"DIFFERENCE": 0, "NOTE": 1, "MATCH": 2}
    return sorted(rows, key=lambda row: priority[row["状态"]])


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    """将复核明细写入 UTF-8 CSV。"""
    fields = [
        "统计量",
        "适用标准",
        "声称值",
        "来源",
        "计算数据来源",
        "显示小数位",
        "按报告模型复现值",
        "按推荐模型重算值",
        "按报告显示值",
        "按推荐显示值",
        "显示一致",
        "推荐一致",
        "状态",
        "差异类型",
        "评分条目",
        "说明",
    ]
    if any("时间组" in row for row in rows):
        fields.insert(1, "时间组")
    if any("被测量" in row for row in rows):
        fields.insert(0, "被测量")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
