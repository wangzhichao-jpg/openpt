# SPDX-License-Identifier: Apache-2.0
"""声称值与模型对照；严格显示位数和末位容差分开。"""

import csv
import math
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

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
        value = result.get("算法A", {}).get("x" if name == "x*" else "s")
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
    except (ValueError, TypeError, InvalidOperation):
        raise ValueError("报告声称值显示小数位须为0至12的整数") from None
    if match is False:
        categories.append("VALUE_MISMATCH")
        if name.startswith("z:"):
            note = (note + "；原因待底稿确认").lstrip("；")
    # 缺乏数据时不能断言所有模型均不能复现。
    return {
        "统计量": name,
        "声称值": claim,
        "来源": source,
        "显示小数位": digits,
        "按报告模型复现值": float(model_value) if isinstance(model_value, Decimal) else model_value,
        "按推荐模型重算值": float(recommended) if isinstance(recommended, Decimal) else recommended,
        "显示一致": match,
        "状态": "NOT_EVALUATED" if match is None else "MATCH" if match else "DIFFERENCE",
        "差异类型": "|".join(dict.fromkeys(categories)),
        "评分条目": item,
        "说明": note,
    }


def review(
    data: dict[str, Any], result: dict[str, Any], mapping: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """比较 GL002 和 GL003 计算结果、报告模型和声称值。"""
    mapping = mapping or {"homogeneity": "均匀性与稳定性评估", "performance": "能力统计量计算"}
    rows = []
    models = {c.get("model") for c in data["claims"] if c.get("name") == "t"}
    for claim in data["claims"]:
        name = claim["name"]
        model = claim.get("model") or "recommended"
        try:
            digits = int(claim["digits"])
        except (ValueError, TypeError):
            raise ValueError("报告声称值显示小数位须为0至12的整数") from None
        reproduced, rec, note = _values(data, result, claim)
        if name == "Ss" and result.get("均匀性", {}).get("Ss_pass") is False:
            limit = result["均匀性"]["threshold"]
            note = f"样品间标准差超过 0.3σ：{rec} > {limit}"
        types = []
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
        row = _row(
            name, claim["value"], digits, claim["source"], reproduced, rec, note, types, item
        )
        if name == "t" and row["显示一致"] is False:
            group = claim.get("timegroup") or "稳定期"
            try:
                candidates = [
                    stability(data["stability"].get("基线"), data["stability"][group], model=m)["t"]
                    for m in ("unit_pooled", "repeats_pooled", "repeats_welch")
                ]
                if model == "displayed_summary":
                    candidates.append(reproduced)
                if all(
                    v is not None and display(v, digits) != display(claim["value"], digits)
                    for v in candidates
                ):
                    row["差异类型"] += "|NOT_REPRODUCIBLE"
            except (ValueError, KeyError):
                pass  # 模型无法计算时不推断全部模型均不复现。
        rows.append(row)
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
    cfg = data["config"]
    if cfg.get("sigma_composite") not in (None, "") and cfg.get("sigma") not in (None, ""):
        ss = float(cfg.get("sigma_ss") or result.get("均匀性", {}).get("Ss", 0))
        composite = math.hypot(float(cfg["sigma"]), ss)
        reported_sigma = cfg.get("reported_stability_sigma")
        source_note = (
            "稳定性报告使用合成标准差"
            if reported_sigma == cfg["sigma_composite"]
            else (
                "稳定性报告使用原标准差"
                if reported_sigma == cfg["sigma"]
                else "稳定性所用标准差待确认"
            )
        )
        rows.append(
            _row(
                "合成标准差",
                float(cfg["sigma_composite"]),
                int(cfg.get("sigma_composite_digits") or 1),
                str(cfg.get("sigma_source") or "输入配置"),
                composite,
                composite,
                "合成标准差用途需确认；" + source_note,
                ["SIGMA_COMPOSITE"],
                mapping.get("homogeneity", "均匀性与稳定性评估"),
            )
        )
    return rows


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
        "状态",
        "差异类型",
        "评分条目",
        "说明",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
