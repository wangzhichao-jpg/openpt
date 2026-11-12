# SPDX-License-Identifier: Apache-2.0
"""导入与只读检查共用的数据形态规则。"""

import json
from collections.abc import Collection
from typing import Any

from ..config.catalog import ENUMS

STABILITY_METHOD_ALIASES = {
    "两均值": "two_sample",
    "单均值": "one_sample",
    "均值差法（GL003 5.3）": "mean_difference",
    "回归趋势法": "regression_trend",
}


BOOLEAN_ENUMS = {
    "strict_homogeneity",
    "reference_uncertainty_negligible",
    "algorithm_a_simplified",
    "independent",
    "hom_in_base",
    "stab_in_base",
    "trans_in_base",
    "trans_in_stab",
    "trend_plot",
}
ASSIGNED_ENUMS = {
    "method": "assigned_method",
    "consensus_method": "consensus_method",
    "hom_source": "hom_source",
    "hom_mapping": "hom_mapping",
    "stab_mapping": "stab_mapping",
    "trans_mapping": "trans_mapping",
    "stability_disposition": "stability_disposition",
    "independent": "independent",
    "hom_in_base": "hom_in_base",
    "stab_in_base": "stab_in_base",
    "trans_in_base": "trans_in_base",
    "trans_in_stab": "trans_in_stab",
}


def enum_problem(field: str, value: Any, *, assigned: bool = False) -> str | None:
    """统一工作簿可选枚举校验，不对自由文字及嵌套配置臆断。"""
    key = ASSIGNED_ENUMS.get(field) if assigned else field
    if key not in ENUMS or value in (None, ""):
        return None
    if key == "stability_method":
        value = STABILITY_METHOD_ALIASES.get(value, value) if isinstance(value, str) else value
    if key in BOOLEAN_ENUMS:
        if isinstance(value, bool) or value in ("TRUE", "FALSE", "启用", "关闭"):
            return None
    elif isinstance(value, str) and value in ENUMS[key]:
        return None
    return f"{field} 配置无效，可选值：" + "、".join(ENUMS[key])


def period_enum_problem(value: Any) -> str | None:
    """即使未选择 GB/T 模式，也不得静默接受非法的逐时点枚举。"""
    if value in (None, ""):
        return None

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                raise ValueError("重复键")
            result[key] = item
        return result

    try:
        periods = json.loads(value, object_pairs_hook=pairs) if isinstance(value, str) else value
    except (ValueError, TypeError):
        return "逐时点配置须为有效 JSON 且不得重复键"
    if not isinstance(periods, dict) or not all(
        isinstance(k, str) and isinstance(v, dict) for k, v in periods.items()
    ):
        return "逐时点配置须为对象，且每个时间组须为对象"
    for entry in periods.values():
        if "kind" in entry and enum_problem("stability_period_options.kind", entry["kind"]):
            return "逐时点 kind 应为 storage 或 transport"
    return None


def insufficient_units(count: int) -> bool:
    """单因子方差分析和当前稳定性计算至少需要两个单元。"""
    return count < 2


def stability_structure_problem(
    groups: Collection[str],
    method: str,
    baseline_source: str,
    has_homogeneity: bool,
    reference: Any,
    standard: str,
    *,
    requires_reference: bool = True,
) -> tuple[str, str] | None:
    """返回稳定性计算所需数据的首个结构问题。"""
    if not groups:
        return None
    if baseline_source not in ENUMS["baseline_source"]:
        return "INVALID_CONFIG", "baseline_source 应为 homogeneity 或 baseline_group"
    if method not in ENUMS["stability_method"]:
        return "INVALID_CONFIG", "未知稳定性方法"
    if method == "regression_trend":
        return "INVALID_CONFIG", "回归趋势法使用趋势稳定性工作表，不能混用稳定性工作表"
    if method == "mean_difference":
        if not any(name != "基线" for name in groups):
            return "MISSING_GROUP", "均值差法须提供至少一个稳定性时间组"
    elif "稳定期" not in groups or (method == "two_sample" and "基线" not in groups):
        return "MISSING_GROUP", "稳定性须指定基线及稳定期组"
    if method == "one_sample" and requires_reference and reference in (None, ""):
        return "MISSING_CONFIG", "单样本检验需要参考值"
    if standard == "gbt28043" and method not in ("two_sample", "mean_difference"):
        return "INVALID_CONFIG", "GB/T 28043 稳定性模式需要两组样品"
    if method == "mean_difference" or standard == "gbt28043":
        if baseline_source == "homogeneity" and not has_homogeneity:
            return "MISSING_GROUP", "所选基线来源没有均匀性数据"
        if baseline_source == "baseline_group" and "基线" not in groups:
            return "MISSING_GROUP", "所选基线来源没有基线组数据"
    return None


def insufficient_replicates(count: int, minimum: int) -> bool:
    """工作表校验和矩阵计算使用同一最小重复数判断。"""
    return count < minimum


def insufficient_homogeneity_replicates(count: int) -> bool:
    """常规方差分析要求每个均匀性单元至少两次重复。"""
    return insufficient_replicates(count, 2)
