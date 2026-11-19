# SPDX-License-Identifier: Apache-2.0
"""稳定性逐组准则的界面及报告显示，不参与计算。"""

from typing import Any

from ..formatting import display_value

METHODS = {
    "one_sample": ("单样本 t 检验", "GL003 5.2.1", "t 检验"),
    "two_sample": ("两样本 t 检验", "GL003 5.2.2", "t 检验"),
    "mean_difference": ("均值差法", "GL003 5.3", "0.3σ"),
}
SOURCES = {"homogeneity": "均匀性数据", "baseline_group": "稳定性基线组"}


def selected_periods(result: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """返回所选主标准的时间组。"""
    gbt = result.get("GB/T稳定性") or {}
    if gbt:
        return True, gbt
    groups = {}
    if result.get("稳定性"):
        groups[result.get("稳定性时间组") or "稳定期"] = result["稳定性"]
    groups.update(result.get("其他稳定性") or {})
    return False, groups


def has_period_overrides(groups: dict[str, Any]) -> bool:
    """只有实际存在逐组设置时才增加显示。"""
    return any(
        field.get("source") == "逐组设置"
        for item in groups.values()
        for field in item.get("criterion_settings", {}).values()
        if isinstance(field, dict)
    )


def period_fields(item: dict[str, Any], gbt: bool, sig: int = 4) -> dict[str, str]:
    """生成各字段的显示值及来源清单。"""
    settings = item.get("criterion_settings") or {}

    def field(key: str, default: Any = None) -> Any:
        return settings.get(key, {}).get("value", default)

    def marked(key: str, value: str) -> str:
        return value + ("（逐组设置）" if settings.get(key, {}).get("source") == "逐组设置" else "")

    kind = {"storage": "稳定性", "transport": "运输"}.get(
        field("kind"), str(field("kind") or "未提供")
    )
    source = SOURCES.get(field("baseline_source"), str(field("baseline_source") or "未提供"))
    source_text = marked("baseline_source", source)
    if gbt:
        method = "GB/T 28043"
        rule = marked(
            "rule", {"basic": "基本判据", "extended": "扩展判据"}.get(field("rule"), "未提供")
        )
        basis = marked("basis", {"sigma_pt": "σ_pt", "delta_e": "δE"}.get(field("basis"), "未提供"))
        delta = field("delta_e")
        delta_text = marked("delta_e", display_value(delta, sig) if delta is not None else "—")
    else:
        method_value = field("stability_method", item.get("method"))
        method_name, rule, basis = METHODS.get(
            method_value, (str(method_value or "未提供"), "未提供", "未提供")
        )
        method = marked("stability_method", method_name)
        delta_text = "不适用"
        if method_value == "one_sample":
            source_text = "不适用（单样本使用参考值）"
    labels = {
        "kind": "类型",
        "stability_method": "GL003参考方法" if gbt else "方法",
        "rule": "GB/T规则" if gbt else "GB/T规则（未使用）",
        "basis": "GB/T依据" if gbt else "GB/T依据（未使用）",
        "delta_e": "δE" if gbt else "δE（未使用）",
        "u2": "u2" if gbt else "u2（未使用）",
        "baseline_source": "基线配置",
    }
    origins = (
        "方法：标准模式；" if gbt else "判据规则：由方法确定；依据：由方法确定；"
    ) + "；".join(
        f"{label}：{settings.get(key, {}).get('source', '未提供')}" for key, label in labels.items()
    )
    return {
        "kind": marked("kind", kind),
        "method": method,
        "rule": rule,
        "basis": basis,
        "delta_e": delta_text,
        "baseline_source": source_text,
        "origins": origins,
    }
