# SPDX-License-Identifier: Apache-2.0
"""为模板和公开示例生成填写提示与联动冲突标识。"""

from copy import deepcopy
from typing import Any

from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from ..config.catalog import ENUMS
from ..config.field_labels import ASSIGNED_LABELS, field_key, field_label
from ..config.rules import ASSIGNED_BOOLEANS, ASSIGNED_ENUMS, METHOD_BOOLEANS, METHOD_NUMBERS
from ..config.workbook_guidance import SCENARIOS

METHOD_EXTRA = {
    "sigma": "均匀性和稳定性判据标准差",
    "criterion_standard": "判据标准模式",
    "criterion_sigma_source": "判据标准差来源",
    "quantile_method": "分位数算法",
    "algorithm_s_input_type": "算法S输入类型",
    "display_value_decimals": "量值显示小数位",
}
TEXT_FIELDS = {
    "source",
    "uncertainty_source",
    "sigma_procedure",
    "stability_disposition_reason",
    "sigma_source",
    "reference_source",
    "trend_source",
    "known_components",
    "expert_values",
    "trend_short_series",
    "trend_long_series",
}
JSON_FIELDS = {"stability_period_options", "transfer_en_map"}
RELATIONS = {
    "method": "选择定值方式；source 与 uncertainty_source 分别填写。",
    "source": "指定值如何得到，不是标准不确定度的来源；关联 method。",
    "uncertainty_source": "指定值基础标准不确定度如何评定；关联 uncertainty。",
    "value": "reference、certified 等须填写；参加者公议由程序计算。",
    "uncertainty": "外部值的基础标准不确定度；known_components 不可同时填。",
    "known_components": "known 可填逗号分隔的非负标准不确定度；不得同时填 uncertainty。",
    "expert_values": "仅 expert_consensus 适用，至少两个逗号分隔数值。",
    "sigma_final": "自动 σ_pt 时须留空；手工填写须登记 sigma_procedure。",
    "sigma_temporary": "自动 σ_pt 时须留空；临时值不能作为显式判据最终值。",
    "sigma_procedure": "填写 σ_pt 确定依据；自动计算会附加程序说明。",
    "sigma_pt_method": "niqr 需选 quantile_method；"
    "自动计算须清空手工 sigma_final 和 sigma_temporary。",
    "sigma_pt_sig_digits": "仅自动 σ_pt 使用，按 GB/T 8170 一次修约；留空不修约。",
    "quantile_method": "NIQR 自动确定 σ_pt 时必须显式选择；"
    "linear 对应 Excel INC，weibull 对应 EXC。",
    "criterion_sigma_source": "选 sigma_pt 须清空方法配置 sigma，并有最终 σ_pt。",
    "sigma": "criterion_sigma_source=sigma_pt 时须留空。",
    "hom_source": "gbt_ss 须选 gbt28043、登记 hom_mapping，且 u_hom 留空或零。",
    "hom_mapping": "引用 gbt_ss 时选 assigned、sigma_prime 或 both，须检查重复计入。",
    "u_hom": "引用 gbt_ss 时不得同时填写非零手工 u_hom。",
    "algorithm_s_input_type": "算法 S 作 σ_pt 时须选 standard_deviation；极差不能直接使用。",
    "stability_period_options": "推荐使用稳定性时间组配置表；同组同字段不得重复设置。",
    "consensus_method": "关联 method=participant_consensus；median 的 NIQR 使用 quantile_method。",
    "stab_mapping": "指定 u_stab 的归属；须结合 stab_in_base 防止重复计入。",
    "stab_in_base": "说明 uncertainty 中是否已含 u_stab；结合 stab_mapping 审核。",
    "hom_in_base": "说明 uncertainty 中是否已含 u_hom；结合 hom_mapping 审核。",
    "u_stab": "与 stab_mapping、stab_in_base 联动；不由稳定性均值差自动估计。",
    "u_trans": "与 trans_mapping、trans_in_base、trans_in_stab 联动。",
    "trans_mapping": "登记 u_trans 的归属；同时检查 trans_in_base 和 trans_in_stab。",
    "trans_in_base": "说明 uncertainty 是否已包含运输分量；与 trans_mapping 联动。",
    "trans_in_stab": "说明 u_stab 是否已包含运输分量；不要与 u_trans 重复计入。",
    "U_assigned": "En 可使用，须结合 k_assigned、uncertainty 和分量映射核对。",
    "k_assigned": "关联 U_assigned，用于说明扩展不确定度的包含因子。",
    "independent": "ζ 等评价需要核实参加者结果与指定值的相关性；关联 method。",
    "stability_disposition": "与稳定性判据结果及 stability_disposition_reason 联动。",
    "stability_disposition_reason": "登记 stability_disposition 的书面依据，不自动证明审批有效。",
    "alpha": "与 criterion_standard、stability_method 及显著性检验相关。",
    "strict_homogeneity": "与 gl003_hom_criterion、replicate_type 联动，单测不适用。",
    "stability_method": "与 baseline_source、reference、stability_design 和时间组配置联动。",
    "reference": "one_sample 稳定性方法的参考值；关联 reference_source。",
    "assigned": "旧版方法配置的参加者评价指定值；不要与指定值表的 method 混淆。",
    "sigma_pt": "旧版评价标准差；sigma 留空时可沿用；与指定值表字段分别登记。",
    "algorithm_a_rule": "控制算法 A；与 consensus_method 和 sigma_pt_method 关联。",
    "display_z_decimals": "控制 z 等统计量显示，不改变计算值；关联 display_value_decimals。",
    "display_sig_digits": "控制有效数字显示；关联 display_value_decimals，不改变计算值。",
    "display_value_decimals": "控制量值小数位；留空使用 display_sig_digits。",
    "sigma_source": "说明方法配置 sigma 的来源；关联 sigma_stage。",
    "sigma_stage": "说明方法配置 sigma 是临时还是最终值；关联 sigma_source。",
    "observation_level": "与 stability_method 和 stability_design 联动；all_repeats 仅供复核。",
    "stability_design": "与 stability_method 及参考值独立性有关，配对设计须审核。",
    "reference_uncertainty_negligible": "单样本法须审核 reference 的不确定度能否忽略。",
    "reference_source": "说明 reference 的来源；与 stability_method 关联。",
    "score_type": "选择参加者评价统计量；所需 σ_pt、u 和 k 随统计量不同。",
    "algorithm_s_stop_rule": "控制算法S的停止规则；关联 algorithm_s_tolerance。",
    "algorithm_s_tolerance": "仅绝对容差停止规则使用；关联 algorithm_s_stop_rule。",
    "algorithm_s_max_iterations": "限制算法S迭代；关联 algorithm_s_stop_rule。",
    "criterion_standard": "gbt_ss 只能配合 gbt28043；另关联 gbt_hom_rule 和 gbt_stability_rule。",
    "stability_u1": "GB/T 稳定性扩展判据的基线均值标准不确定度；关联 stability_u2。",
    "stability_u2": "GB/T 稳定期扩展判据的后续均值标准不确定度；其他组须分别登记。",
    "report_standard": "复核报告所用标准；与 criterion_standard 比较，不改变主判据。",
    "gbt_hom_rule": "GB/T 均匀性预选判据；关联 criterion_standard 和 gbt_criterion_basis。",
    "gbt_stability_rule": "GB/T 稳定性预选判据；扩展时关联 stability_u1、stability_u2。",
    "delta_e": "最大允许偏差；关联 gbt_criterion_basis 和逐组依据。",
    "gbt_criterion_basis": "选择 sigma_pt 或 delta_e 为基本判据依据；关联对应数值。",
    "baseline_source": "稳定性基线来源；关联 stability_method 与逐时间组设置。",
    "report_stability_method": "报告声明的方法；与 stability_method 比较，仅用于复核。",
    "replicate_type": "重复或单测设计；单测不支持 GL003 严格均匀性判据。",
    "layout": "决定均匀性和稳定性数据按长表或宽表读取。",
    "gl003_hom_criterion": "GL003 主判据；与 strict_homogeneity、replicate_type 联动。",
    "report_gl003_hom_criterion": "报告声明的 GL003 判据；与 gl003_hom_criterion 比较。",
    "trend_aggregate": "趋势序列聚合方式；与 stability_method=regression_trend 联动。",
    "trend_short_series": "短期趋势序列；与 trend_short_span 配对。",
    "trend_short_span": "短期时长；与 trend_short_series 的时间单位一致。",
    "trend_long_series": "长期趋势序列；与 trend_long_span 配对。",
    "trend_long_span": "长期时长；与 trend_long_series 的时间单位一致。",
    "trend_source": "趋势法依据；关联 stability_method 与趋势稳定性表。",
    "design": "传递标准设计须填写传递标准配置和复测表。",
    "transfer_en_map": "参加者与传递标准点映射；关联 score_type=En。",
    "trend_plot": "趋势绘图；关联 stability_method=regression_trend。",
    "mean1": "报告基线均值；与 mean2、s1、s2、n1、n2 一起用于复核。",
    "mean2": "报告后续均值；与 mean1、s1、s2、n1、n2 一起用于复核。",
    "s1": "报告基线标准差；与 mean1、mean2、s2、n1、n2 一起用于复核。",
    "s2": "报告后续标准差；与 mean1、mean2、s1、n1、n2 一起用于复核。",
    "n1": "报告基线样本数；与 mean1、mean2、s1、s2、n2 一起用于复核。",
    "n2": "报告后续样本数；与 mean1、mean2、s1、s2、n1 一起用于复核。",
    "sigma_ss": "报告登记的均匀性分量；与 sigma_composite 一起用于复核。",
    "sigma_composite": "报告登记的合成标准差；与 sigma_ss 一起用于复核。",
    "reported_stability_sigma": "报告稳定性判据标准差；用于与 sigma 比较。",
}
METHOD_MEANINGS = {
    "mean1": "报告基线均值",
    "mean2": "报告后续均值",
    "s1": "报告基线标准差",
    "s2": "报告后续标准差",
    "n1": "报告基线样本数",
    "n2": "报告后续样本数",
    "sigma": "均匀性和稳定性判据标准差",
    "sigma_pt": "能力评价标准差",
    "assigned": "旧版参加者评价指定值",
    "sigma_ss": "报告均匀性标准差分量",
    "sigma_composite": "报告合成标准差",
    "reported_stability_sigma": "报告稳定性判据标准差",
    "display_sig_digits": "显示有效数字位数",
}
CASE_SUFFIX = "（随包示例说明；复制为自己的项目时请改写或删除本行）"
SCENARIO_MARKER = "常见场景怎么填"


def _position(ws: Any) -> dict[str, int]:
    return {
        field_key(ws.cell(i, 1).value): i for i in range(2, ws.max_row + 1) if ws.cell(i, 1).value
    }


def _allowance(key: str, assigned: bool) -> str:
    if key in ASSIGNED_BOOLEANS or key in METHOD_BOOLEANS:
        return "允许：TRUE/FALSE；方法配置亦可填启用/关闭。"
    enum = ASSIGNED_ENUMS.get(key) if assigned else key
    if enum in ENUMS:
        return "允许：" + "、".join(ENUMS[enum]) + "。"
    if key == "alpha":
        return "允许：大于 0 且小于 1 的有限数。"
    if key in {"sigma", "sigma_pt", "sigma_final", "sigma_temporary", "delta_e", "k_assigned"}:
        return "允许：正有限数，或留空。"
    if key in {
        "uncertainty",
        "u_hom",
        "u_stab",
        "u_trans",
        "U_assigned",
        "stability_u1",
        "stability_u2",
    }:
        return "允许：非负有限数，或留空。"
    if key in {"display_value_decimals", "display_z_decimals"}:
        return "允许：0 至 12 的整数，或留空。"
    if key == "display_sig_digits":
        return "允许：1 至 15 的整数，或留空。"
    if key in JSON_FIELDS:
        return "允许：符合填写说明的 JSON 对象。"
    if key in TEXT_FIELDS:
        return (
            "允许：文字；分量及专家列表使用逗号分隔数值。"
            if key in ("known_components", "expert_values")
            else "允许：文字。"
        )
    if key == "sigma_pt_sig_digits":
        return "允许：正整数，或留空。"
    if key in METHOD_NUMBERS or key in {
        "value",
        "uncertainty",
        "sigma_final",
        "sigma_temporary",
        "u_hom",
        "u_stab",
        "u_trans",
        "U_assigned",
        "k_assigned",
    }:
        return "允许：有限数字，具体正负及范围见填写说明。"
    return "允许：按字段说明填写；详见填写说明。"


def _validation(
    ws: Any, row: int, key: str, assigned: bool, label: str, existing: list[Any]
) -> None:
    address = f"B{row}"
    prior = next((dv for dv in existing if address in dv.sqref), None)
    if prior:
        dv = deepcopy(prior)
        dv.sqref = address
    else:
        enum = ASSIGNED_ENUMS.get(key) if assigned else key
        options = ENUMS.get(enum or "")
        if options:
            dv = DataValidation(
                type="list", formula1='"' + ",".join(options) + '"', allow_blank=True
            )
        else:
            dv = DataValidation(type="custom", formula1="TRUE", allow_blank=True)
        dv.add(address)
    meaning = (
        ASSIGNED_LABELS.get(key, label)
        if assigned
        else METHOD_MEANINGS.get(key, label.split("（", 1)[0])
    )
    relation = RELATIONS.get(key, "见填写说明中的常见场景。")
    prompt = f"含义：{meaning}。{_allowance(key, assigned)}关联：{relation}"
    dv.promptTitle = f"{meaning[:17]}（{key}）"[:32]
    dv.prompt = prompt if len(prompt) <= 255 else prompt[:245] + "…详见填写说明。"
    dv.showInputMessage = True
    ws.add_data_validation(dv)


def _ref(sheet: str, row: int, current_sheet: str) -> str:
    cell = f"$B${row}"
    return cell if sheet == current_sheet else f"INDIRECT(\"'{sheet}'!{cell}\")"


def add_scenario_guidance(book: Any, *, example: bool) -> None:
    """幂等追加场景及示例复制提醒。"""
    if "填写说明" not in book.sheetnames:
        return
    ws = book["填写说明"]
    if not example:
        for row in range(ws.max_row, 1, -1):
            if ws.cell(row, 1).value == "本案例":
                ws.delete_rows(row)
    else:
        for row in range(2, ws.max_row + 1):
            if ws.cell(row, 1).value == "本案例":
                cell = ws.cell(row, 2)
                if CASE_SUFFIX not in str(cell.value or ""):
                    cell.value = str(cell.value or "") + CASE_SUFFIX
    existing = {str(ws.cell(row, 1).value or "") for row in range(2, ws.max_row + 1)}
    if SCENARIO_MARKER not in existing:
        ws.append([SCENARIO_MARKER, "按下列场景填写；字段的完整要求见本表参数说明。"])
        for title, description in SCENARIOS:
            ws.append([title, description])
            ws.cell(ws.max_row, 2).alignment = Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[ws.max_row].height = min(
                409, max(30, 15 * (1 + len(description) // 50))
            )
    ws.column_dimensions["A"].width = max(ws.column_dimensions["A"].width or 0, 25)
    ws.column_dimensions["B"].width = max(ws.column_dimensions["B"].width or 0, 80)


def apply_workbook_hints(book: Any, *, example: bool = False) -> None:
    """保留值，更新标签、输入信息与可跨表计算的条件格式。"""
    add_scenario_guidance(book, example=example)
    if "方法配置" not in book.sheetnames:
        return
    method = book["方法配置"]
    if "指定值与不确定度" not in book.sheetnames:
        book.create_sheet("指定值与不确定度").append(["字段", "值"])
    assigned = book["指定值与不确定度"]
    for key, label in METHOD_EXTRA.items():
        if key not in _position(method):
            method.append([f"{label}（{key}）", None])
    for key in ASSIGNED_LABELS:
        if key not in _position(assigned):
            assigned.append([field_label(key), None])
    for row in range(2, assigned.max_row + 1):
        key = field_key(assigned.cell(row, 1).value)
        if key in ASSIGNED_LABELS:
            assigned.cell(row, 1).value = field_label(key)
    for ws in (method, assigned):
        if ws is None:
            continue
        ws.cell(1, 3, "填写提示（冲突时标红）")
        if not any(cell.value == "（选填）" for cell in ws[1]):
            ws.cell(1, max(4, ws.max_column + 1), "（选填）")
        ws.column_dimensions["A"].width = 48
        ws.column_dimensions["B"].width = 26
        ws.column_dimensions["C"].width = 58
        previous = list(ws.data_validations.dataValidation)
        ws.data_validations.dataValidation = []
        for row in range(2, ws.max_row + 1):
            label = ws.cell(row, 1).value
            if not label:
                continue
            key = field_key(label)
            _validation(ws, row, key, ws.title == "指定值与不确定度", str(label), previous)
        ws.conditional_formatting._cf_rules.clear()
    positions = {method.title: _position(method), assigned.title: _position(assigned)}
    conditions = [
        (
            [(assigned.title, "hom_source"), (method.title, "criterion_standard")],
            lambda r: f'AND({r[0]}="gbt_ss",{r[1]}<>"gbt28043")',
            "gbt_ss 须选 gbt28043。",
        ),
        (
            [(assigned.title, "hom_source"), (assigned.title, "hom_mapping")],
            lambda r: f'AND({r[0]}="gbt_ss",OR({r[1]}="none",{r[1]}=""))',
            "gbt_ss 须登记有效的 hom_mapping。",
        ),
        (
            [(assigned.title, "hom_source"), (assigned.title, "u_hom")],
            lambda r: f'AND({r[0]}="gbt_ss",{r[1]}<>"",{r[1]}<>0)',
            "gbt_ss 不可同时填写非零 u_hom。",
        ),
        (
            [(assigned.title, "sigma_pt_method"), (assigned.title, "sigma_final")],
            lambda r: f'AND({r[0]}<>"",{r[0]}<>"manual",{r[1]}<>"")',
            "自动 σ_pt 与手工 sigma_final 冲突。",
        ),
        (
            [(assigned.title, "sigma_pt_method"), (assigned.title, "sigma_temporary")],
            lambda r: f'AND({r[0]}<>"",{r[0]}<>"manual",{r[1]}<>"")',
            "自动 σ_pt 与手工 sigma_temporary 冲突。",
        ),
        (
            [(method.title, "criterion_sigma_source"), (method.title, "sigma")],
            lambda r: f'AND({r[0]}="sigma_pt",{r[1]}<>"")',
            "选择 sigma_pt 作判据时须清空 sigma。",
        ),
        (
            [(assigned.title, "sigma_pt_method"), (method.title, "quantile_method")],
            lambda r: f'AND({r[0]}="niqr",{r[1]}="")',
            "NIQR 作 σ_pt 须显式选择 quantile_method。",
        ),
    ]
    notes: dict[tuple[str, int], list[str]] = {}
    red = PatternFill(fill_type="solid", fgColor="FFC7CE")
    for fields, build, note in conditions:
        for sheet, key in fields:
            ws = book[sheet]
            row = positions[sheet][key]
            refs = [_ref(s, positions[s][k], sheet) for s, k in fields]
            rule = FormulaRule(formula=[build(refs)], fill=red)
            ws.conditional_formatting.add(f"B{row}:C{row}", rule)
            notes.setdefault((sheet, row), []).append(note)
    for (sheet, row), messages in notes.items():
        book[sheet].cell(row, 3, "冲突提示：" + "；".join(dict.fromkeys(messages)))
