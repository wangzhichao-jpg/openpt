# SPDX-License-Identifier: Apache-2.0
"""计算入口与输入预检共用的配置规则。"""

import json
import math
from dataclasses import dataclass
from typing import Any, TypeGuard

from ..io.shape import period_enum_problem
from .catalog import ENUMS

RULE_CODES: dict[str, str] = {
    "ASSIGNED_ENUM": "指定值枚举无效",
    "ASSIGNED_BOOL": "指定值布尔标识无效",
    "DISPOSITION_REASON_TYPE": "稳定性处置依据类型无效",
    "SOURCE_REQUIRED": "指定值或不确定度来源缺失",
    "LIST_METHOD": "指定值列表不适用当前方法",
    "LIST_INVALID": "指定值列表格式或数值无效",
    "COMPONENT_CONFLICT": "制备分量与不确定度冲突",
    "EXPERT_CONFLICT": "专家结果与预评定值冲突",
    "VALUE_REQUIRED": "指定值缺失",
    "UNCERTAINTY_REQUIRED": "指定值不确定度缺失",
    "ASSIGNED_NUMBER": "指定值数值无效",
    "ASSIGNED_NUMBER_NO_METHOD": "未选择指定值方法时数值非有限数",
    "SIGMA_PROCEDURE": "能力评定标准差确定程序缺失",
    "HOM_SS_MAPPING": "引用 ss 未登记分量映射",
    "HOM_SS_MANUAL": "引用 ss 与手工分量冲突",
    "HOM_SS_STANDARD": "引用 ss 的标准模式不匹配",
    "CONFIG_BOOL": "方法配置布尔值无效",
    "CONFIG_ENUM": "方法配置枚举无效",
    "CONFIG_NUMBER": "方法配置数值非有限数",
    "ALPHA_RANGE": "显著性水平超出范围",
    "CONFIG_POSITIVE": "方法配置数值应为正",
    "DISPLAY_VALUE_DECIMALS": "量值显示小数位无效",
    "PERIOD_OPTIONS": "逐时点配置无效",
    "PERIOD_CRITERIA": "逐时间组准则配置无效",
    "TRANSFER_MAP": "参加者传递标准映射无效",
    "DELTA_REQUIRED": "所选依据缺少 delta_e",
}


@dataclass(frozen=True)
class RuleIssue:
    """一个可定位的配置问题。"""

    field: str
    value: Any
    message: str
    allowed: str
    hint: str
    code: str

    def __post_init__(self) -> None:
        if self.code not in RULE_CODES:
            raise ValueError(f"未知规则代码：{self.code}")


ASSIGNED_ENUMS = {
    "method": "assigned_method",
    "consensus_method": "consensus_method",
    "hom_source": "hom_source",
    "hom_mapping": "hom_mapping",
    "stab_mapping": "stab_mapping",
    "trans_mapping": "trans_mapping",
    "stability_disposition": "stability_disposition",
}
ASSIGNED_BOOLEANS = ("independent", "hom_in_base", "stab_in_base", "trans_in_base", "trans_in_stab")
METHOD_BOOLEANS = (
    "strict_homogeneity",
    "reference_uncertainty_negligible",
    "algorithm_a_simplified",
    "trend_plot",
)
METHOD_NUMBERS = (
    "alpha",
    "sigma",
    "reference",
    "assigned",
    "sigma_pt",
    "delta_e",
    "stability_u1",
    "stability_u2",
    "algorithm_a_tolerance",
    "algorithm_a_max_iterations",
    "display_z_decimals",
    "display_sig_digits",
    "display_mean_decimals",
    "display_ss_decimals",
    "z_satisfactory",
    "z_unsatisfactory",
    "en_limit",
    "algorithm_s_tolerance",
    "algorithm_s_max_iterations",
    "mean1",
    "mean2",
    "s1",
    "s2",
    "n1",
    "n2",
    "sigma_composite",
    "sigma_ss",
    "sigma_composite_digits",
    "reported_stability_sigma",
)


def _number(value: Any) -> TypeGuard[int | float]:
    try:
        return (
            not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
        )
    except OverflowError:
        return False


def _bool(value: Any, *, method: bool = False) -> bool:
    return isinstance(value, bool) or (
        isinstance(value, str)
        and value in (("TRUE", "FALSE", "启用", "关闭") if method else ("TRUE", "FALSE"))
    )


def check_assigned(
    values: dict[str, Any], method_config: dict[str, Any] | None = None
) -> list[RuleIssue]:
    """检查指定值表的静态配置；不推断数据相关结论。"""
    issues: list[RuleIssue] = []

    def add(field: str, message: str, allowed: str, hint: str, code: str) -> None:
        issues.append(RuleIssue(field, values.get(field), message, allowed, hint, code))

    method = values.get("method")
    for field, enum in ASSIGNED_ENUMS.items():
        value = values.get(field)
        if value not in (None, "") and (not isinstance(value, str) or value not in ENUMS[enum]):
            add(field, f"{field} 配置无效", "、".join(ENUMS[enum]), "选择允许的值", "ASSIGNED_ENUM")
    for field in ASSIGNED_BOOLEANS:
        value = values.get(field)
        if value not in (None, "") and not _bool(value):
            add(field, f"{field} 须为布尔值", "TRUE 或 FALSE", "修改为布尔值", "ASSIGNED_BOOL")
    reason = values.get("stability_disposition_reason")
    if reason not in (None, "") and not isinstance(reason, str):
        add(
            "stability_disposition_reason",
            "稳定性处置依据须为文字",
            "文字",
            "填写书面依据",
            "DISPOSITION_REASON_TYPE",
        )
    if method in (None, ""):
        # 无定值方法时仍检查已填写的数值字段，避免遗漏模板输入错误。
        for field in (
            "value",
            "uncertainty",
            "sigma_temporary",
            "sigma_final",
            "u_hom",
            "u_stab",
            "u_trans",
            "U_assigned",
            "k_assigned",
        ):
            value = values.get(field)
            if value not in (None, "") and not _number(value):
                add(
                    field,
                    f"{field} 必须为有限数",
                    "有限数",
                    "修改数值",
                    "ASSIGNED_NUMBER_NO_METHOD",
                )
        return issues
    for field, message in (
        ("source", "指定值来源必填"),
        ("uncertainty_source", "指定值不确定度来源必填"),
    ):
        value = values.get(field)
        if not isinstance(value, str) or not value.strip():
            add(field, message, "非空文字", "填写来源", "SOURCE_REQUIRED")
    components, experts = values.get("known_components"), values.get("expert_values")
    for field, raw, expected in (
        ("known_components", components, "known"),
        ("expert_values", experts, "expert_consensus"),
    ):
        if raw in (None, ""):
            continue
        if method != expected:
            add(
                field,
                f"{field} 仅适用于 {expected} 方法",
                expected,
                "清空该字段或修改方法",
                "LIST_METHOD",
            )
        try:
            numbers = (
                [float(item.strip()) for item in raw.split(",")] if isinstance(raw, str) else []
            )
            valid = bool(numbers) and all(math.isfinite(n) for n in numbers)
            valid = valid and (field != "known_components" or all(n >= 0 for n in numbers))
            valid = valid and (field != "expert_values" or len(numbers) >= 2)
        except (ValueError, OverflowError):
            valid = False
        if not valid:
            add(
                field,
                "列表格式或数值无效",
                "逗号分隔的有限数；专家至少两个，分量非负",
                "修改列表",
                "LIST_INVALID",
            )
    if (
        method == "known"
        and components not in (None, "")
        and values.get("uncertainty") not in (None, "")
    ):
        add(
            "known_components",
            "已知值不可同时输入基础不确定度和制备分量",
            "二者只能填一个",
            "清空其中一个",
            "COMPONENT_CONFLICT",
        )
    if (
        method == "expert_consensus"
        and experts not in (None, "")
        and (values.get("value") not in (None, "") or values.get("uncertainty") not in (None, ""))
    ):
        add(
            "expert_values",
            "专家结果与预先评定的值或不确定度不可同时输入",
            "二者不可同时填写",
            "清空冲突字段",
            "EXPERT_CONFLICT",
        )
    if method in ("known", "certified", "reference", "expert_consensus") and not (
        method == "expert_consensus" and experts not in (None, "")
    ):
        if values.get("value") in (None, ""):
            add("value", "该方法须填写指定值", "有限数", "填写指定值", "VALUE_REQUIRED")
        if not (method == "known" and components not in (None, "")) and values.get(
            "uncertainty"
        ) in (None, ""):
            add(
                "uncertainty",
                "该方法须填写标准不确定度",
                "非负有限数",
                "填写标准不确定度",
                "UNCERTAINTY_REQUIRED",
            )
    for field in (
        "value",
        "uncertainty",
        "sigma_temporary",
        "sigma_final",
        "u_hom",
        "u_stab",
        "u_trans",
        "U_assigned",
        "k_assigned",
    ):
        value = values.get(field)
        if value in (None, ""):
            continue
        positive = field in ("sigma_temporary", "sigma_final", "k_assigned")
        nonnegative = field in ("uncertainty", "u_hom", "u_stab", "u_trans", "U_assigned")
        if not _number(value) or (positive and value <= 0) or (nonnegative and value < 0):
            allowed = "正有限数" if positive else "非负有限数" if nonnegative else "有限数"
            add(field, f"{field} 数值无效", allowed, "修改数值", "ASSIGNED_NUMBER")
    if any(values.get(field) not in (None, "") for field in ("sigma_temporary", "sigma_final")):
        value = values.get("sigma_procedure")
        if not isinstance(value, str) or not value.strip():
            add(
                "sigma_procedure",
                "须登记 σ_pt 确定程序",
                "非空文字",
                "填写确定程序",
                "SIGMA_PROCEDURE",
            )
    if values.get("hom_source") == "gbt_ss":
        if values.get("hom_mapping") not in ("assigned", "sigma_prime", "both"):
            add(
                "hom_mapping",
                "hom_source=gbt_ss 时引用 ss 须明确登记分量映射",
                "assigned、sigma_prime 或 both",
                "选择分量映射",
                "HOM_SS_MAPPING",
            )
        if values.get("u_hom") not in (None, "", 0, 0.0):
            add(
                "u_hom",
                "引用 ss 时不得同时手工输入 u_hom",
                "空白或零",
                "清空手工 u_hom",
                "HOM_SS_MANUAL",
            )
        # 标准模式属于方法表，由调用方按该表定位。
    return issues


def check_cross(assigned: dict[str, Any], config: dict[str, Any]) -> list[RuleIssue]:
    """检查指定值表与方法配置表之间的静态约束。"""
    if (
        assigned.get("method") not in (None, "")
        and assigned.get("hom_source") == "gbt_ss"
        and config.get("criterion_standard") != "gbt28043"
    ):
        return [
            RuleIssue(
                "criterion_standard",
                config.get("criterion_standard"),
                "hom_source=gbt_ss 时 criterion_standard 须为 gbt28043",
                "gbt28043",
                "修改方法配置的标准模式",
                "HOM_SS_STANDARD",
            )
        ]
    return []


def period_criteria_problem(values: dict[str, Any]) -> str | None:
    """检查逐组准则；JSON 结构错误由 PERIOD_OPTIONS 报告。"""
    raw = values.get("stability_period_options")
    if raw in (None, ""):
        return None
    try:
        entries = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return None
    if not isinstance(entries, dict) or not all(isinstance(v, dict) for v in entries.values()):
        return None
    enums = {
        "rule": ("basic", "extended"),
        "basis": ("sigma_pt", "delta_e"),
        "stability_method": ("one_sample", "two_sample", "mean_difference"),
        "baseline_source": ("homogeneity", "baseline_group"),
    }
    allowed = {"kind", "u2", "delta_e", *enums}
    global_method = values.get("stability_method") or "two_sample"
    for name, entry in entries.items():
        if set(entry) - allowed:
            return f"{name}：未知逐时间组字段：{', '.join(sorted(set(entry) - allowed))}"
        for field, options in enums.items():
            if field in entry and entry[field] not in options:
                if field == "stability_method" and entry[field] == "regression_trend":
                    return f"{name}：趋势法只能全局设置"
                return f"{name}：{field} 应为 {'、'.join(options)}"
        for field, positive in (("delta_e", True), ("u2", False)):
            if (
                field in entry
                and not (field == "u2" and entry[field] in (None, ""))
                and (
                    not _number(entry[field])
                    or (entry[field] <= 0 if positive else entry[field] < 0)
                )
            ):
                return f"{name}：{field} 须为{'正' if positive else '非负'}有限数"
        if "stability_method" in entry and values.get("criterion_standard", "gl003") == "gbt28043":
            return f"{name}：逐组 stability_method 仅适用于 GL003"
        if (values.get("criterion_standard") or "gl003") == "gl003" and any(
            key in entry for key in ("rule", "basis", "delta_e")
        ):
            return f"{name}：rule、basis、delta_e 逐组设置仅适用于 GB/T 模式"
        method = entry.get("stability_method", global_method)
        if (
            "stability_method" in entry
            and not entry.get("baseline_source")
            and values.get("baseline_source") in (None, "")
            and (method == "mean_difference") != (global_method == "mean_difference")
        ):
            return (
                f"{name}：须明确登记 baseline_source；homogeneity 使用均匀性数据，"
                "baseline_group 使用稳定性基线组"
            )
    return None


def check_period_groups(values: dict[str, Any], groups: Any) -> list[RuleIssue]:
    """检查逐时点配置是否引用已存在的非基线组。"""
    raw = values.get("stability_period_options")
    if raw in (None, "") or period_enum_problem(raw):
        return []
    entries = json.loads(raw) if isinstance(raw, str) else raw
    unknown = set(entries) - (set(groups) - {"基线"})
    if not unknown:
        return []
    return [
        RuleIssue(
            "stability_period_options",
            raw,
            "逐时点配置包含不存在的时间组：" + "、".join(sorted(unknown)),
            "稳定性表中已登记的时间组",
            "修改时间组名称",
            "PERIOD_CRITERIA",
        )
    ]


def check_method_config(values: dict[str, Any]) -> list[RuleIssue]:
    """检查方法表内可静态判断的字段。"""
    issues: list[RuleIssue] = []

    def add(field: str, message: str, allowed: str, hint: str, code: str) -> None:
        issues.append(RuleIssue(field, values.get(field), message, allowed, hint, code))

    for field, value in values.items():
        if value in (None, ""):
            continue
        if field in METHOD_BOOLEANS:
            if not _bool(value, method=True):
                add(field, f"{field} 须为布尔值", "TRUE 或 FALSE", "修改为布尔值", "CONFIG_BOOL")
        elif field in ENUMS and field not in ASSIGNED_ENUMS and field not in ASSIGNED_BOOLEANS:
            aliases = {"两均值", "单均值", "均值差法（GL003 5.3）", "回归趋势法"}
            valid = isinstance(value, str) and (
                value in ENUMS[field] or (field == "stability_method" and value in aliases)
            )
            if not valid:
                message = (
                    "GB/T 判据应为 basic 或 extended"
                    if field in ("gbt_hom_rule", "gbt_stability_rule")
                    else f"{field} 配置无效"
                )
                add(field, message, "、".join(ENUMS[field]), "选择允许的值", "CONFIG_ENUM")
    for field in METHOD_NUMBERS:
        value = values.get(field)
        if value not in (None, "") and not _number(value):
            add(field, f"{field} 必须为有限数", "有限数", "修改数值", "CONFIG_NUMBER")
    places = values.get("display_value_decimals")
    if places not in (None, "") and (
        not _number(places) or places != int(places) or not 0 <= places <= 12
    ):
        add(
            "display_value_decimals",
            "量值显示小数位须为 0 至 12 的整数",
            "0 至 12 的整数",
            "修改小数位",
            "DISPLAY_VALUE_DECIMALS",
        )
    alpha = values.get("alpha")
    if _number(alpha) and not 0 < alpha < 1:
        add("alpha", "alpha 必须在 0 和 1 之间", "0 < alpha < 1", "修改显著性水平", "ALPHA_RANGE")
    for field in ("sigma", "sigma_pt", "delta_e"):
        value = values.get(field)
        if _number(value) and value <= 0:
            add(field, f"{field} 必须为正有限数", "正有限数", "修改数值", "CONFIG_POSITIVE")
    period_problem = period_enum_problem(values.get("stability_period_options"))
    if period_problem:
        add(
            "stability_period_options",
            period_problem,
            "有效逐时点 JSON 配置",
            "修正逐时点配置",
            "PERIOD_OPTIONS",
        )
    criteria_problem = period_criteria_problem(values)
    if criteria_problem:
        add(
            "stability_period_options",
            criteria_problem,
            "有效逐时间组准则",
            "修改逐时间组配置",
            "PERIOD_CRITERIA",
        )
    raw = values.get("transfer_en_map")
    if raw not in (None, ""):
        try:

            def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
                result: dict[str, Any] = {}
                for key, value in items:
                    if key in result:
                        raise ValueError("重复参加者编号")
                    result[key] = value
                return result

            mapping = json.loads(raw, object_pairs_hook=unique) if isinstance(raw, str) else raw
            if not isinstance(mapping, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()
            ):
                raise ValueError("映射须为字符串对象")
        except (ValueError, TypeError):
            add(
                "transfer_en_map",
                "transfer_en_map 须为有效 JSON 对象",
                "参加者编号到标准器|校准点的 JSON 对象",
                "修正 JSON 格式及映射",
                "TRANSFER_MAP",
            )
    if (
        values.get("criterion_standard") == "gbt28043"
        and values.get("gbt_criterion_basis") == "delta_e"
        and values.get("delta_e") in (None, "")
    ):
        add(
            "delta_e",
            "所选 gbt_criterion_basis 缺少对应输入",
            "正有限数",
            "填写 delta_e，或选择有对应输入的判据依据",
            "DELTA_REQUIRED",
        )
    return issues
