# SPDX-License-Identifier: Apache-2.0
"""工作簿常见场景：填写说明与手册共用。"""

SCENARIOS = [
    (
        "参加者公议定值（算法 A / 中位值）",
        "必填：参加者结果至少两行；指定值表 method=participant_consensus、"
        "source、uncertainty_source。"
        "选填：consensus_method=robust_mean（默认算法 A）或 median；median 可选 quantile_method，"
        "留空 linear；σ_pt 与分量按实际登记。不要填：预先评定的 value、uncertainty 不用于此公议；"
        "不要混填专家列表或制备分量。",
    ),
    (
        "单一实验室或参考实验室定值",
        "必填：method=reference、value、uncertainty、source、uncertainty_source；"
        "value 为外部评定值，uncertainty 为其基础标准不确定度。选填：σ_pt、独立分量及其映射；"
        "适用 GB/T 28043-2019 7.5。不要填：known_components、expert_values；"
        "不要把不确定度来源误写进指定值来源。",
    ),
    (
        "有证标准样品定值",
        "必填：method=certified、value、uncertainty、source、uncertainty_source。"
        "选填：σ_pt、均匀性及稳定性分量与映射。CRM 差值法须先按批准程序在外部计算指定值及其"
        "基础标准不确定度，再分别填入 value、uncertainty；在来源中说明证书及差值法。"
        "不要填：known_components、expert_values；程序不自动计算 CRM 差值。",
    ),
    (
        "已知值 / 配方定值",
        "必填：method=known、value、source、uncertainty_source；"
        "uncertainty 或 known_components 二选一。"
        "选填：known_components 为逗号分隔的非负标准不确定度分量；σ_pt 及其他独立分量按实际登记。"
        "不要填：uncertainty 与 known_components 不可同时填写，expert_values 不适用。",
    ),
    (
        "σ_pt 手工或自动",
        "必填：手工时 sigma_pt_method 留空或 manual，填写 sigma_final 或 sigma_temporary 及 "
        "sigma_procedure；自动时选 niqr、algorithm_a、made 或 algorithm_s，清空 sigma_final 和 "
        "sigma_temporary。选填：sigma_pt_sig_digits 为正整数；按 GB/T 8170 四舍六入五成双一次修约，"
        "不得连续修约；sigma_procedure 可填写用户说明。niqr 须显式选 quantile_method：linear 对应 "
        "Excel QUARTILE.INC/PERCENTILE.INC，weibull 对应 QUARTILE.EXC/PERCENTILE.EXC，"
        "也可选 hazen、median_unbiased；algorithm_s 须填算法S表并设 "
        "algorithm_s_input_type=standard_deviation。不要填：自动与手工 σ_pt 不可同时填；"
        "极差不能作为 σ_pt。",
    ),
    (
        "判据 σ 手工或取 σ_pt",
        "必填：手工判据在方法配置填写 sigma；或明确设 criterion_sigma_source=sigma_pt 并登记"
        "最终 sigma_final 或自动计算 σ_pt。选填：sigma_source、sigma_stage 按实际登记。"
        "不要填：选择 sigma_pt 作判据时不得同时填写方法配置 sigma；指定值表的临时 σ_pt 不能替代"
        "最终值。未显式选择时不会自动从指定值表回填。",
    ),
    (
        "GL003 与 GB/T 28043 模式",
        "必填：criterion_standard 选 gl003 或 gbt28043，并按所选方法提供均匀性、稳定性和判据数据。"
        "选填：GL003 可选 gl003_hom_criterion；GB/T 可选 basic/extended 及依据，扩展稳定性判据"
        "按需填写 stability_u1、stability_u2。引用 GB/T ss 时须设 hom_source=gbt_ss、"
        "criterion_standard=gbt28043，并设 hom_mapping=assigned、sigma_prime 或 both。"
        "不要填：引用 ss 时不填手工 u_hom；不可用 gl003 引用 gbt_ss。",
    ),
    (
        "稳定期与运输期分别设置",
        "必填：稳定性表填写各时间组数据，两样本或基线组方式还须填写基线；"
        "“稳定性时间组配置”逐行填写存在的时间组名称。选填：kind=storage 或 transport；"
        "GB/T 可逐组选择 rule、basis、delta_e、u2，GL003 可选 stability_method、baseline_source；"
        "空白继承全局或默认。不要填：不要在时间组配置表与 stability_period_options JSON 对同组"
        "同字段重复设置；不能把一个后续组 u2 自动用于其他组。",
    ),
]


def scenario_markdown() -> str:
    """用于手册同步检查。"""
    return "\n\n".join(f"#### {title}\n\n{text}" for title, text in SCENARIOS)
