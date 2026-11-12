# SPDX-License-Identifier: Apache-2.0
"""用户可配置的枚举、声称统计量及报告模型说明。"""

ENUMS: dict[str, tuple[str, ...]] = {
    "decision": ("接受", "退回", "需补充"),
    "stability_method": ("one_sample", "two_sample", "mean_difference", "regression_trend"),
    "trend_aggregate": ("per_series", "time_mean"),
    "design": ("transfer_standard",),
    "stability_window": ("all", "transfer_only"),
    "transfer_mechanism": ("A", "B", "C"),
    "report_stability_method": ("one_sample", "two_sample", "mean_difference", "regression_trend"),
    "baseline_source": ("homogeneity", "baseline_group"),
    "criterion_standard": ("gl003", "gbt28043"),
    "report_standard": ("gl003", "gbt28043"),
    "gl003_hom_criterion": ("f_test", "ss_0.3sigma", "both"),
    "report_gl003_hom_criterion": ("f_test", "ss_0.3sigma", "both"),
    "gbt_hom_rule": ("basic", "extended"),
    "gbt_stability_rule": ("basic", "extended"),
    "gbt_criterion_basis": ("sigma_pt", "delta_e"),
    "observation_level": ("unit_means", "all_repeats"),
    "stability_design": ("independent", "paired", "correlated"),
    "stability_period_options.kind": ("storage", "transport"),
    "sigma_stage": ("temporary", "final"),
    "replicate_type": ("technical", "adjacent_specimens", "other", "single"),
    "layout": ("long", "wide"),
    "algorithm_a_rule": ("gl002", "gbt28043", "absolute", "simplified"),
    "algorithm_s_stop_rule": ("gl002", "absolute"),
    "score_type": ("z", "zprime", "zeta", "En", "D", "D%", "all"),
    "assigned_method": (
        "known",
        "certified",
        "reference",
        "expert_consensus",
        "participant_consensus",
    ),
    "consensus_method": ("robust_mean", "median"),
    "hom_source": ("manual", "gbt_ss"),
    "hom_mapping": ("none", "assigned", "sigma_prime", "both"),
    "stab_mapping": ("none", "assigned", "sigma_prime", "both"),
    "trans_mapping": ("none", "assigned"),
    "stability_disposition": ("pending", "budgeted", "reviewed", "withhold"),
    "候选批次.状态": ("候选", "失败", "选用", "弃用"),
    "strict_homogeneity": ("TRUE", "FALSE"),
    "reference_uncertainty_negligible": ("TRUE", "FALSE"),
    "algorithm_a_simplified": ("TRUE", "FALSE"),
    "independent": ("TRUE", "FALSE"),
    "hom_in_base": ("TRUE", "FALSE"),
    "stab_in_base": ("TRUE", "FALSE"),
    "trans_in_base": ("TRUE", "FALSE"),
    "trans_in_stab": ("TRUE", "FALSE"),
}

CLAIM_NAMES = (
    "F",
    "F值",
    "方差分析F值",
    "Ss",
    "t",
    "x*",
    "s*",
    "NIQR",
    "u(X)",
    "z:编号",
    "zprime:编号",
    "zeta:编号",
    "En:编号",
    "D:编号",
    "D%:编号",
    "均值差",
    "稳定性均值差",
    "|x̄-ȳ|",
    "x̄",
    "xbar",
    "均匀性总平均值",
    "ȳ",
    "ȳ",
    "ybar",
    "稳定性时间组平均值",
    "0.3σ",
    "0.3σ阈值",
    "0.3σ 阈值",
    "均匀性基本限值",
    "均匀性扩展限值",
    "稳定性基本限值",
    "稳定性扩展限值",
    "b1",
    "b0",
    "s(b1)",
    "趋势阈值",
    "趋势X̄",
    "趋势Ȳ",
    "趋势t临界值",
    "趋势结论",
    "Δmax",
    "传递限值",
    "U_E",
    "u_stab",
    "传递结论",
)

HOMOGENEITY_CLAIM_NAMES = frozenset(
    {
        "F",
        "F值",
        "方差分析F值",
        "Ss",
        "t",
        "均值差",
        "稳定性均值差",
        "|x̄-ȳ|",
        "x̄",
        "xbar",
        "均匀性总平均值",
        "ȳ",
        "ȳ",
        "ybar",
        "稳定性时间组平均值",
        "0.3σ",
        "0.3σ阈值",
        "0.3σ 阈值",
        "均匀性基本限值",
        "均匀性扩展限值",
        "稳定性基本限值",
        "稳定性扩展限值",
    }
)

REPORT_MODELS: dict[str, str] = {
    "recommended": "按当前推荐模型重算；默认选择。",
    "repeats_pooled": "把重复值合并并采用合并方差，仅用于复现报告，须核查伪重复。",
    "repeats_welch": "把重复值合并并采用非齐方差模型，仅用于复现报告。",
    "displayed_summary": "对 t 使用报告中显示的均值、标准差和样本数，核查中间修约。",
    "absolute": "对算法 A 使用绝对容差候选停止规则，须核实报告规则。",
    "gbt28043": "按 GB/T 模式复现限值或算法 A 停止规则；须确认具体统计量适用。",
    "gl003": "按 GL003 模式复现均匀性或稳定性统计量与限值。",
}


def template_rows() -> list[tuple[str, str]]:
    """生成填写说明中的参数与模型清单。"""
    rows = [
        (
            name,
            ("指定值与不确定度表的 method；" if name == "assigned_method" else "")
            + "可选值："
            + "、".join(values),
        )
        for name, values in ENUMS.items()
    ]
    rows.append(("报告声称统计量", "、".join(CLAIM_NAMES)))
    rows.extend(("报告模型 " + name, description) for name, description in REPORT_MODELS.items())
    return rows


def markdown() -> str:
    """生成手册中可由测试逐字核对的参考清单。"""
    lines = ["### 枚举参数", "", "| 字段 | 可选值 |", "|---|---|"]
    lines.extend(
        f"| `{name}` | " + "、".join(f"`{value}`" for value in values) + " |"
        for name, values in ENUMS.items()
    )
    lines.extend(
        [
            "",
            "### 报告声称统计量",
            "",
            "、".join(f"`{name}`" for name in CLAIM_NAMES),
            "",
            "### 报告模型",
            "",
            "| 取值 | 含义和适用场景 |",
            "|---|---|",
        ]
    )
    lines.extend(f"| `{name}` | {description} |" for name, description in REPORT_MODELS.items())
    lines.extend(
        [
            "",
            "带 `:编号` 的统计量须填写实际参加者编号；均值、均值差和阈值可以填写时间组。",
            "`assigned_method` 对应“指定值与不确定度”表的 `method`；"
            "`stability_period_options.kind` 在逐时点 JSON 中填写。",
            "布尔值采用 TRUE/FALSE，模板中的“启用/关闭”会转换为布尔值。"
            "σ 来源等自由文本不是固定枚举。",
        ]
    )
    return "\n".join(lines)
