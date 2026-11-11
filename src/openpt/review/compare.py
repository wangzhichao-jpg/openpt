# SPDX-License-Identifier: Apache-2.0
"""声称值与模型对照；严格显示位数和末位容差分开。"""

import csv
import math
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from ..core.robust import algorithm_a
from ..core.stability import analyze as stability
from ..core.stability import summary_t


def display(value: float | Decimal | None, digits: int) -> Decimal | None:
    """按报告显示位数进行十进制四舍五入。"""
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def _t_reproduction(
    data: dict[str, Any], result: dict[str, Any], claim: dict[str, Any]
) -> tuple[Any, Any, str]:
    """按 GL003 5.2.2 对指定时点计算报告和推荐模型。"""
    cfg = data["config"]
    groups = data["stability"]
    name = claim.get("timegroup") or "稳定期"
    model = claim.get("model") or "recommended"
    selected = (
        result.get("稳定性", {}) if name == "稳定期" else result.get("其他稳定性", {}).get(name, {})
    )
    recommended = selected.get("t")
    if model in ("repeats_pooled", "repeats_welch"):
        report_result = stability(groups.get("基线"), groups[name], model=model)
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
    return (recommended if model == "recommended" else None), recommended, ""


def _values(
    data: dict[str, Any], result: dict[str, Any], claim: dict[str, Any]
) -> tuple[Any, Any, str]:
    name = claim["name"]
    cfg = data["config"]
    if name in ("F", "Ss"):
        value = result.get("均匀性", {}).get(name)
        return value, value, ""
    if name in ("x*", "s*"):
        key = "x" if name == "x*" else "s"
        value = result.get("算法A", {}).get(key)
        if claim.get("model") == "absolute" and data.get("participants"):
            alternative = algorithm_a([p["value"] for p in data["participants"]], rule="absolute")
            if not alternative.converged:
                return None, value, "绝对容差模型未收敛，未评价；报告停止规则待底稿确认"
            return alternative[key], value, "绝对容差作为候选报告模型，原报告停止规则待底稿确认"
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
) -> dict[str, Any]:
    try:
        if not 0 <= digits <= 12:
            raise ValueError("显示位数超出范围")
        match = (
            display(model_value, digits) == display(claim, digits)
            if model_value is not None
            else None
        )
        recommended_match = (
            display(recommended, digits) == display(claim, digits)
            if recommended is not None
            else None
        )
    except (ValueError, TypeError, InvalidOperation):
        raise ValueError("报告数值或显示小数位无效") from None
    # 对只有一个可计算模型的量，显示不一致才构成数值差异；多模型量在调用处判定。
    if match is False and name not in ("t", "x*", "s*"):
        categories.append("VALUE_MISMATCH")
        note = (note + "；原因待底稿确认").lstrip("；")
    if match is None:
        note = (note + "；未评价：缺少输入或所选模型无法计算").lstrip("；")
    status = (
        "DIFFERENCE"
        if "VALUE_MISMATCH" in categories
        else (
            "NOTE"
            if match is not True or recommended_match is False or categories or note
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
        "显示一致": match,
        "推荐一致": recommended_match,
        "状态": status,
        "差异类型": "|".join(dict.fromkeys(categories)),
        "评分条目": item,
        "说明": note,
    }


def _candidate_models(
    data: dict[str, Any], result: dict[str, Any], claim: dict[str, Any], digits: int
) -> bool | None:
    """全部可计算且均不一致为真；有候选一致为假；资料不足为未定。"""
    group = claim.get("timegroup") or "稳定期"
    try:
        candidates = [
            stability(data["stability"].get("基线"), data["stability"][group], model=m)["t"]
            for m in ("unit_pooled", "repeats_pooled", "repeats_welch")
        ]
        if group == "稳定期":
            summary_claim = {**claim, "model": "displayed_summary"}
            summary, _, _ = _t_reproduction(data, result, summary_claim)
            if summary is not None:
                candidates.append(summary)
        if any(
            v is not None and display(v, digits) == display(claim["value"], digits)
            for v in candidates
        ):
            return False
        return True if all(v is not None for v in candidates) else None
    except (ValueError, KeyError):
        return None


def _algorithm_candidates(
    data: dict[str, Any], name: str, claim: float, digits: int
) -> bool | None:
    """检查算法 A 三种停止规则；数据不足时不推断无法复现。"""
    try:
        values = [p["value"] for p in data["participants"]]
        results = [algorithm_a(values, rule=rule) for rule in ("gl002", "absolute", "simplified")]
        valid = [r[name] for r in results if r.converged and r.status == "OK"]
        if any(display(value, digits) == display(claim, digits) for value in valid):
            return False
        return True if len(valid) == len(results) else None
    except (ValueError, KeyError):
        return None


def _review_claim(
    data: dict[str, Any],
    result: dict[str, Any],
    claim: dict[str, Any],
    models: set[Any],
    mapping: dict[str, str],
) -> list[dict[str, Any]]:
    """复核一条声称值并产生必要的附加中间量差异。"""
    name = claim["name"]
    model = claim.get("model") or "recommended"
    try:
        digits = int(claim["digits"])
        if isinstance(claim["digits"], bool) or float(claim["digits"]) != digits:
            raise ValueError("显示位数必须为整数")
    except (ValueError, TypeError, OverflowError):
        raise ValueError("报告声称值显示小数位须为0至12的整数") from None
    reproduced, rec, note = _values(data, result, claim)
    types = []
    if name == "Ss" and result.get("均匀性", {}).get("Ss_pass") is False:
        note = f"样品间标准差超过 0.3σ：{rec} > {result['均匀性']['threshold']}"
        cfg = data["config"]
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
    item = (
        mapping.get("homogeneity", "均匀性与稳定性评估")
        if name in ("F", "Ss", "t")
        else mapping.get("performance", "能力统计量计算")
    )
    row = _row(name, claim["value"], digits, claim["source"], reproduced, rec, note, types, item)
    if name == "t" and row["显示一致"] is False:
        candidate_result = _candidate_models(data, result, claim, digits)
        if candidate_result is True:
            row["差异类型"] = "|".join(
                filter(None, (row["差异类型"], "VALUE_MISMATCH", "NOT_REPRODUCIBLE"))
            )
            row["状态"] = "DIFFERENCE"
        elif candidate_result is False:
            row["说明"] += "；其他候选模型可按显示位数复现"
        else:
            row["说明"] += "；候选模型数据不足，未能确认数值差异"
    if name in ("x*", "s*"):
        if row["显示一致"] is True and row["推荐一致"] is False:
            row["差异类型"] = "|".join(filter(None, (row["差异类型"], "STOP_RULE_SENSITIVITY")))
            row["状态"] = "NOTE"
            row["说明"] += "；停止规则敏感，不据此认定报告错误"
        elif row["显示一致"] is False:
            key = "x" if name == "x*" else "s"
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
    rows = [row]
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
    data: dict[str, Any], result: dict[str, Any], mapping: dict[str, str]
) -> dict[str, Any] | None:
    """核查声称的标准差合成及其稳定性用途。"""
    cfg = data["config"]
    if cfg.get("sigma_composite") in (None, "") or cfg.get("sigma") in (None, ""):
        return None
    ss = cfg.get("sigma_ss")
    if ss in (None, ""):
        ss = result.get("均匀性", {}).get("Ss")
    composite = math.hypot(float(cfg["sigma"]), float(ss)) if ss is not None else None
    reported_sigma = cfg.get("reported_stability_sigma")
    if reported_sigma == cfg["sigma_composite"]:
        source_note = "稳定性报告使用合成标准差"
    elif reported_sigma == cfg["sigma"]:
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
        mapping.get("homogeneity", "均匀性与稳定性评估"),
    )


def _design_rows(result: dict[str, Any], mapping: dict[str, str]) -> list[dict[str, Any]]:
    """将稳定性抽样设计提示单独列入复核清单。"""
    periods = []
    if result.get("稳定性"):
        periods.append(("稳定期", result["稳定性"]))
    periods.extend(result.get("其他稳定性", {}).items())
    rows = []
    for name, values in periods:
        warnings = values.get("design_warnings", [])
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
                "评分条目": mapping.get("homogeneity", "均匀性与稳定性评估"),
                "说明": "；".join(warnings),
            }
        )
    return rows


def review(
    data: dict[str, Any], result: dict[str, Any], mapping: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """比较 GL002 和 GL003 计算结果、报告模型和声称值。"""
    mapping = mapping or {"homogeneity": "均匀性与稳定性评估", "performance": "能力统计量计算"}
    models = {c.get("model") for c in data["claims"] if c.get("name") == "t"}
    rows = []
    for claim in data["claims"]:
        rows.extend(_review_claim(data, result, claim, models, mapping))
    composite = _composite_row(data, result, mapping)
    if composite is not None:
        rows.append(composite)
    rows.extend(_design_rows(result, mapping))
    priority = {"DIFFERENCE": 0, "NOTE": 1, "MATCH": 2}
    return sorted(rows, key=lambda row: priority[row["状态"]])


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    """将复核明细写入 UTF-8 CSV。"""
    fields = [
        "统计量",
        "声称值",
        "来源",
        "显示小数位",
        "按报告模型复现值",
        "按推荐模型重算值",
        "显示一致",
        "推荐一致",
        "状态",
        "差异类型",
        "评分条目",
        "说明",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
