# SPDX-License-Identifier: Apache-2.0
"""导入与只读检查共用的数据形态规则。"""

from collections.abc import Collection
from typing import Any

STABILITY_METHOD_ALIASES = {
    "两均值": "two_sample",
    "单均值": "one_sample",
    "均值差法（GL003 5.3）": "mean_difference",
}


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
    if baseline_source not in ("homogeneity", "baseline_group"):
        return "INVALID_CONFIG", "baseline_source 应为 homogeneity 或 baseline_group"
    if method not in ("one_sample", "two_sample", "mean_difference"):
        return "INVALID_CONFIG", "未知稳定性方法"
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


def insufficient_homogeneity_replicates(count: int) -> bool:
    """常规方差分析要求每个均匀性单元至少两次重复。"""
    return count < 2
