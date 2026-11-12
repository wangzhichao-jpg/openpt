# SPDX-License-Identifier: Apache-2.0
"""面向复核人员的 DOCX 计算书。"""

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from openpyxl.utils.cell import column_index_from_string, coordinate_from_string, get_column_letter

from .. import __version__


def _shown(value: Any, digits: int = 4, places: int | None = None) -> str:
    """输出指定精度，空值和布尔值使用中文。"""
    if value is None:
        return "未评价（未提供数据或无法计算）"
    if isinstance(value, bool):
        return "通过" if value else "不通过"
    if isinstance(value, (int, float)) and places is not None:
        return f"{value:.{places}f}"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:#.{digits}g}"
    return str(value)


def _table(doc: Any, headers: list[str], rows: list[list[Any]]) -> None:
    """创建带底纹和重复表头的可跨页表格。"""
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    widths = [1.45, 1.35, 1.55, 1.55, 1.35, 2.5, 4.0, 2.0] if len(headers) == 8 else None
    if widths:
        table.autofit = False
        for column, width in zip(table.columns, widths, strict=True):
            column.width = Cm(width)
    header = table.rows[0]
    trpr = header._tr.get_or_add_trPr()
    repeat = OxmlElement("w:tblHeader")
    repeat.set(qn("w:val"), "true")
    trpr.append(repeat)
    for index, (cell, title) in enumerate(zip(header.cells, headers, strict=True)):
        if widths:
            cell.width = Cm(widths[index])
        cell.text = title
        tcpr = cell._tc.get_or_add_tcPr()
        shade = OxmlElement("w:shd")
        shade.set(qn("w:fill"), "D9EAF7")
        tcpr.append(shade)
    for values in rows:
        row = table.add_row()
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        cells = row.cells
        for index, (cell, value) in enumerate(zip(cells, values, strict=True)):
            if widths:
                cell.width = Cm(widths[index])
            cell.text = str(value)
            if isinstance(value, (int, float)) or (
                isinstance(value, str) and value.lstrip("-+").replace(".", "", 1).isdigit()
            ):
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT


def _data_places(data: dict[str, Any]) -> int:
    """以已导入数字的十进制表示估计原始小数位。"""
    recorded = data.get("data_decimal_places")
    if isinstance(recorded, int):
        return min(12, recorded + 1)
    values = [v for group in data.get("homogeneity", []) for v in group]
    for groups in data.get("stability", {}).values():
        values.extend(v for group in groups for v in group)
    if not values:
        return 2
    places = []
    for value in values:
        exponent = Decimal(str(value)).as_tuple().exponent
        places.append(-exponent if isinstance(exponent, int) else 0)
    return min(12, max(0, max(places)) + 1)


def _source_ranges(sources: list[str]) -> list[str]:
    """将单元格位置合并为同一工作表的连续矩形区域。"""
    grouped: dict[str, dict[int, set[int]]] = {}
    fallback = []
    for source in sources:
        try:
            sheet, address = source.rsplit("!", 1)
            column, row = coordinate_from_string(address)
            index = column_index_from_string(column)
            grouped.setdefault(sheet, {}).setdefault(index, set()).add(row)
        except (ValueError, TypeError):
            fallback.append(source)
    ranges = []
    for sheet, columns in grouped.items():
        intervals: dict[tuple[int, int], list[int]] = {}
        for column, positions in columns.items():
            ordered = sorted(positions)
            start = previous = ordered[0]
            for current in [*ordered[1:], ordered[-1] + 2]:
                if current != previous + 1:
                    intervals.setdefault((start, previous), []).append(column)
                    start = current
                previous = current
        for (start_row, end_row), indices in intervals.items():
            ordered_columns = sorted(indices)
            start_col = previous_col = ordered_columns[0]
            for current_col in [*ordered_columns[1:], ordered_columns[-1] + 2]:
                if current_col != previous_col + 1:
                    left = f"{get_column_letter(start_col)}{start_row}"
                    right = f"{get_column_letter(previous_col)}{end_row}"
                    ranges.append(f"{sheet}!{left}" if left == right else f"{sheet}!{left}:{right}")
                    start_col = current_col
                previous_col = current_col
    return ranges + fallback


def _raw_tables(doc: Any, data: dict[str, Any]) -> None:
    """按单元和重复次数显示均匀性与稳定性原始值。"""
    blocks = [("均匀性", data.get("homogeneity", []), data.get("homogeneity_units", []))]
    blocks.extend(
        (f"稳定性：{key}", value, data.get("stability_units", {}).get(key, []))
        for key, value in data.get("stability", {}).items()
    )
    sources = list(data.get("sources", []))
    sources.extend(p["source"] for p in data.get("participants", []) if p.get("source"))
    for name, groups, unit_ids in blocks:
        if not groups:
            continue
        doc.add_paragraph(name)
        count = max(len(group) for group in groups)
        headers = ["单元编号"] + [f"重复 {i}" for i in range(1, count + 1)]
        _table(
            doc,
            headers,
            [
                [
                    unit_ids[i] if i < len(unit_ids) else str(i + 1),
                    *map(str, row),
                    *([""] * (count - len(row))),
                ]
                for i, row in enumerate(groups)
            ],
        )
    if sources:
        doc.add_paragraph("数据来源：" + "、".join(_source_ranges(sources)))
    else:
        doc.add_paragraph("未提供原始测量值。")
    numeric_sources = data.get("numeric_sources", {})
    if numeric_sources:
        doc.add_paragraph("数值单元格追溯（未经修约）：")
        _table(
            doc,
            ["工作表!单元格", "原始数值"],
            [[location, str(value)] for location, value in numeric_sources.items()],
        )


def _homogeneity(
    doc: Any,
    result: dict[str, Any],
    mean_places: int,
    sig: int,
    ss_places: int,
    alpha: float,
) -> None:
    """按 GL003 4.2、4.3 显示方差分析和用途判据。"""
    h = result.get("均匀性")
    doc.add_heading("均匀性方差分析", 1)
    if not h:
        doc.add_paragraph("未提供均匀性数据。")
        return
    _table(
        doc,
        ["变异来源", "自由度", "平方和", "均方", "F", "F 临界值", "p"],
        [
            [
                "样品间",
                h["df_between"],
                _shown(h["SS_between"]),
                _shown(h["MS_between"]),
                _shown(h["F"], sig),
                _shown(h["F_critical"], sig),
                _shown(h["p"], sig),
            ],
            [
                "样品内",
                h["df_within"],
                _shown(h["SS_within"]),
                _shown(h["MS_within"]),
                "—",
                "—",
                "—",
            ],
        ],
    )
    _table(
        doc,
        ["统计量", "结果"],
        [
            ["总平均值", _shown(h["mean"], places=mean_places)],
            ["F 值", _shown(h["F"], sig)],
            ["F 临界值", _shown(h["F_critical"], sig)],
            ["p 值", _shown(h["p"], sig)],
            ["样品间标准差", _shown(h["Ss"], places=ss_places)],
            [
                "用途判据限值",
                _shown(h["threshold"], places=ss_places)
                if h["threshold"] is not None
                else "未评价（未提供 σ）",
            ],
        ],
    )
    if len(set(h.get("counts", []))) > 1:
        doc.add_paragraph(
            "扩展方法：不平衡随机效应单因子 ANOVA；n₀=(N-Σnᵢ²/N)/(g-1)，"
            "Ss²=max(0,(MS组间-MS组内)/n₀)。出处：Searle 等，Variance Components，"
            "1992，单因子随机效应模型，出处页码待专家核对；GL003 4.3 仅给出平衡设计。"
            f" 本例 n₀={_shown(h['n0'])}。"
        )
    _homogeneity_conclusion(doc, h, sig, ss_places, alpha)


def _homogeneity_conclusion(
    doc: Any,
    h: dict[str, Any],
    sig: int,
    ss_places: int,
    alpha: float,
) -> None:
    """按 GL003 4.2 和 4.3 说明统计量、判定与未评价原因。"""
    if h["F"] is None:
        doc.add_paragraph("按 GL003 4.2：未评价，组内均方为零或数值超出范围，F 无法计算。")
    else:
        relation = "<" if h["F_pass"] else "≥"
        judgement = (
            "样品间无显著性差异，按 F 检验判定均匀"
            if h["F_pass"]
            else "样品间存在显著性差异，按 F 检验判定不均匀"
        )
        doc.add_paragraph(
            f"按 GL003 4.2：F={_shown(h['F'], sig)} {relation} "
            f"F{alpha:g}({h['df_between']},{h['df_within']})={_shown(h['F_critical'], sig)}，"
            f"{judgement}；按未修约值及相对容差 1e-12 比较。"
        )
    if h["threshold"] is None:
        doc.add_paragraph(f"并列提示：Ss={_shown(h['Ss'], places=ss_places)}；未评价：未提供 σ。")
    else:
        relation = "≤" if h["Ss_pass"] else ">"
        judgement = "通过" if h["Ss_pass"] else "不通过"
        doc.add_paragraph(
            f"并列提示（GL003 4.3）：Ss={_shown(h['Ss'], places=ss_places)} {relation} "
            f"0.3σ={_shown(h['threshold'], places=ss_places)}，用途判据{judgement}。"
        )
    if h.get("strict"):
        conclusion = (
            "未评价：F 或 Ss 判据无法计算" if h["conclusion"] is None else _shown(h["conclusion"])
        )
        doc.add_paragraph("严格配置综合结论：" + conclusion + "。")
    stage = {"temporary": "临时值", "final": "最终值"}.get(str(h.get("sigma_stage")), "未登记")
    doc.add_paragraph(
        f"σ 阶段：{stage}；来源：{h.get('sigma_source') or '未登记'}；"
        f"用途判据状态：{h['Ss_status']}。"
    )
    doc.add_paragraph("计算状态：" + str(h["status"]))
    for warning in h.get("design_warnings", []) + h.get("warnings", []):
        doc.add_paragraph("提示：" + warning)


def _stability_table(doc: Any, name: str, s: dict[str, Any], sig: int) -> None:
    """显示一个时点的稳定性检验。"""
    doc.add_paragraph(name)
    if s.get("status") == "DESIGN_REVIEW":
        doc.add_paragraph("DESIGN_REVIEW：需要经批准的模型，不给出稳定性结论。")
        for warning in s.get("design_warnings", []):
            doc.add_paragraph("设计提示：" + warning)
        return
    if s.get("reference_source"):
        doc.add_paragraph("参考值来源：" + str(s["reference_source"]))
    doc.add_paragraph("实验层级：" + str(s.get("observation_level", "unit_means")))
    doc.add_paragraph("按用户登记的独立设计计算；独立性未由软件自动验证。")
    names = [
        ("均值差", "difference"),
        ("t 值", "t"),
        ("自由度", "df"),
        ("t 临界值", "critical"),
        ("p 值", "p"),
        ("t 检验结论", "pass"),
        ("均值差判据", "mean_difference_pass"),
    ]
    rows = []
    for label, key in names:
        value = s.get(key)
        if value is None and key == "mean_difference_pass":
            shown = "未评价（未提供 σ）"
        elif value is None and key in ("t", "p", "pass"):
            shown = "未评价（标准误为零或统计量不可计算）"
        else:
            shown = _shown(value, sig)
        rows.append([label, shown])
    _table(doc, ["项目", "结果"], rows)
    if s.get("t") is None:
        doc.add_paragraph("t 检验未评价：标准误为零或统计量不可计算。")
    else:
        relation = "<" if s.get("pass") else "≥"
        conclusion = "未发现显著变化" if s.get("pass") else "存在显著变化"
        doc.add_paragraph(
            f"按 GL003 5.2：t={_shown(s['t'], sig)} {relation} "
            f"临界值 {_shown(s.get('critical'), sig)}，{conclusion}。"
        )
    if s.get("threshold") is None:
        doc.add_paragraph("均值差判据未评价：未提供 σ。")
    else:
        relation = "≤" if s.get("mean_difference_pass") else ">"
        conclusion = "通过" if s.get("mean_difference_pass") else "不通过"
        doc.add_paragraph(
            f"按 GL003 5.3：均值差 {_shown(s['difference'], sig)} {relation} "
            f"0.3σ={_shown(s['threshold'], sig)}，判据{conclusion}。"
        )
    doc.add_paragraph("计算状态：" + str(s.get("status", "未评价：计算状态未提供")))
    for warning in s.get("design_warnings", []):
        doc.add_paragraph("设计提示：" + warning)


def _gbt_results(doc: Any, result: dict[str, Any], cfg: dict[str, Any], sig: int) -> None:
    """显示 GB/T 模式的中间量、各项判据及人工设计提示。"""
    doc.add_heading("GB/T 28043-2019 标准模式（主评价）", 1)
    doc.add_paragraph("以下分别给出基本和扩展判据；选择及处置由授权人员决定。")
    doc.add_paragraph(
        f"σ_pt 阶段：{cfg.get('sigma_stage') or '未登记'}；"
        f"来源：{cfg.get('sigma_source') or '未登记'}。"
    )
    h = result.get("GB/T均匀性")
    if h:
        doc.add_paragraph("均匀性：B.2.2 式(B.1)、B.2.3、B.3 式(B.10)。")
        items = [
            ("样品数 g", "g"),
            ("重复数 m", "m"),
            ("总均值", "mean"),
            ("样品均值标准差 sx", "sx"),
            ("样品内标准差 sw", "sw"),
            ("原始方差分量", "variance_raw"),
            ("样品间标准差 ss", "ss"),
            ("σ_pt", "sigma"),
            ("基本限值", "basic_limit"),
            ("基本判据", "basic_pass"),
            ("F1", "f1"),
            ("F2 或 Fm", "f2_or_fm"),
            ("c", "c"),
            ("扩展限值 √c", "extended_limit"),
            ("扩展判据", "extended_pass"),
            ("重复性检查", "repeatability_check"),
        ]
        _table(doc, ["项目", "结果"], [[label, _shown(h.get(key), sig)] for label, key in items])
        doc.add_paragraph("ss=√max(0,sx²-sw²/m)；c=F1(0.3σ_pt)²+F2或Fm·sw²。")
        for warning in h["warnings"]:
            doc.add_paragraph("提示：" + warning)
    for name, s in result.get("GB/T稳定性", {}).items():
        doc.add_paragraph(f"稳定性 {name}：B.5.1 式(B.17)、B.5.2 式(B.18)。")
        items = [
            ("基线均值", "mean1"),
            ("后续均值", "mean2"),
            ("均值差", "difference"),
            ("σ_pt", "sigma"),
            ("基本限值", "basic_limit"),
            ("基本判据", "basic_pass"),
            ("基线均值标准不确定度", "u1"),
            ("后续均值标准不确定度", "u2"),
            ("扩展限值", "extended_limit"),
            ("扩展判据", "extended_pass"),
        ]
        _table(doc, ["项目", "结果"], [[label, _shown(s.get(key), sig)] for label, key in items])
        doc.add_paragraph("扩展限值=0.3σ_pt+2√(u₁²+u₂²)，假设两均值独立。")
        for warning in s["warnings"]:
            doc.add_paragraph("提示：" + warning)
    doc.add_paragraph("以下 GL003 计算仅为参考，不作为本次选定标准的主评价。")


def _other_results(
    doc: Any,
    data: dict[str, Any],
    result: dict[str, Any],
    sig: int,
    mean_places: int,
    z_places: int,
) -> None:
    """显示稳定性、稳健统计和参加者评价。"""
    doc.add_heading("稳定性评价", 1)
    s = result.get("稳定性")
    if s:
        _stability_table(doc, "稳定期", s, sig)
        report_model = result.get("报告层级稳定性")
        if report_model:
            doc.add_paragraph(
                "报告复现层级：all_repeats，仅用于复现，不作推荐结论；"
                f"t={_shown(report_model.get('t'), sig)}，状态={report_model.get('status')}。"
            )
        for name, extra in result.get("其他稳定性", {}).items():
            _stability_table(doc, str(name), extra, sig)
    else:
        doc.add_paragraph("未提供稳定性数据。")
    _robust_results(doc, result, sig, mean_places)
    algorithm_s_result = result.get("算法S")
    if algorithm_s_result:
        doc.add_paragraph(
            "GL002 附录 A.3 式 A.7—A.10：w*=ξ·√[Σmin(wᵢ,ηw*)²/p]；"
            f"w*={_shown(algorithm_s_result['w'], sig)}，"
            f"自由度={algorithm_s_result['df']}，状态={algorithm_s_result['status']}。"
        )
        if "STOP_RULE_SENSITIVITY" in algorithm_s_result.get("warnings", []):
            doc.add_paragraph(
                "STOP_RULE_SENSITIVITY：算法 S 选定规则结果 "
                f"{_shown(algorithm_s_result['w'], 8)}，绝对及相对容差收敛对照 "
                f"{_shown(algorithm_s_result.get('reference_w'), 8)}；"
                "两者第三位有效数字不同，须人工复核。"
            )
        if "REFERENCE_NOT_CONVERGED" in algorithm_s_result.get("warnings", []):
            doc.add_paragraph("算法 S 收敛对照未收敛，停止规则敏感性未评价。")
    niqr = result.get("中位数NIQR")
    if niqr:
        doc.add_paragraph(
            "GL002 附录 A.4：线性插值 type 7，NIQR=0.7413×(Q3-Q1)；"
            f"中位数={_shown(niqr['median'], sig)}，Q1={_shown(niqr['q1'], sig)}，"
            f"Q3={_shown(niqr['q3'], sig)}，NIQR={_shown(niqr['niqr'], sig)}。"
        )
    _assigned_table(doc, result)
    _participant_table(doc, data, result, z_places)


def _robust_results(doc: Any, result: dict[str, Any], sig: int, mean_places: int) -> None:
    """显示 GL002 稳健统计及停止规则敏感性。"""
    doc.add_heading("稳健统计", 1)
    a = result.get("算法A")
    if a:
        names = [
            ("稳健平均值", "x"),
            ("稳健标准差", "s"),
            ("标准不确定度", "u_x"),
            ("迭代次数", "iterations"),
            ("收敛", "converged"),
        ]
        _table(
            doc,
            ["项目", "结果"],
            [
                [label, _shown(a.get(key), sig, places=mean_places if key == "x" else None)]
                for label, key in names
            ],
        )
        rules = {"gl002": "GL002 第三有效位规则", "absolute": "绝对容差", "simplified": "简化法"}
        doc.add_paragraph("停止规则：" + rules.get(a.get("rule"), "未提供"))
        converged = result.get("算法A_收敛对照")
        if converged and not converged.get("converged"):
            doc.add_paragraph("停止规则敏感性未评价：绝对容差对照未收敛。")
        elif converged and (
            _shown(a.get("x"), places=mean_places) != _shown(converged.get("x"), places=mean_places)
            or _shown(a.get("s"), sig) != _shown(converged.get("s"), sig)
        ):
            doc.add_paragraph(
                f"停止规则敏感：选定规则的稳健标准差为 {_shown(a.get('s'), sig)}，"
                f"绝对容差收敛对照为 {_shown(converged.get('s'), sig)}；"
                "两者在显示位数下不同，不据此认定报告错误。"
            )
    else:
        doc.add_paragraph(str(result.get("稳健统计状态", "未提供参加者结果。")))


def _assigned_table(doc: Any, result: dict[str, Any]) -> None:
    """展示 GL002 4.3 定值与扩展方法的不确定度及映射。"""
    assigned = result.get("指定值与不确定度")
    if not assigned:
        return
    doc.add_heading("指定值与不确定度", 1)
    labels = [
        ("定值方法", "method"),
        ("公议计算方法", "consensus_method"),
        ("指定值", "value"),
        ("标准不确定度 u(X)", "u"),
        ("基础标准不确定度", "base_u"),
        ("制备不确定度分量", "known_components"),
        ("专家结果", "expert_values"),
        ("指定值来源", "source"),
        ("不确定度来源", "uncertainty_source"),
        ("指定值扩展不确定度 U(X)", "U_assigned"),
        ("指定值包含因子 k", "k_assigned"),
        ("结果间不相关", "independent"),
        ("临时 σ_pt", "sigma_temporary"),
        ("最终 σ_pt", "sigma_final"),
        ("σ_pt 确定程序", "sigma_procedure"),
        ("评价标准差 σ′", "sigma_prime"),
        ("u_hom", "u_hom"),
        ("均匀性分量映射", "hom_mapping"),
        ("基础值含均匀性分量", "hom_in_base"),
        ("u_stab", "u_stab"),
        ("稳定性分量映射", "stab_mapping"),
        ("基础值含稳定性分量", "stab_in_base"),
        ("状态", "status"),
    ]
    boolean_keys = {"independent", "hom_in_base", "stab_in_base"}
    _table(
        doc,
        ["项目", "结果"],
        [
            [
                label,
                ("是" if assigned[key] else "否")
                if key in boolean_keys and assigned.get(key) is not None
                else _shown(assigned.get(key)),
            ]
            for label, key in labels
        ],
    )
    doc.add_paragraph(assigned.get("formula", ""))
    doc.add_paragraph(
        "扩展方法：u(X)=√(u_base²+Σu分量²)，σ′=√(σ_pt²+Σu分量²)；"
        "假定分量独立；均匀性 σ′ 见 GB/T 28043-2019 B.2.5 式(B.3)，多分量扩展须经批准。"
    )
    for warning in assigned.get("warnings", []):
        doc.add_paragraph("设计提示：" + warning)


def _participant_table(
    doc: Any, data: dict[str, Any], result: dict[str, Any], z_places: int
) -> None:
    """按参加者显示 z、评价及原始数据来源。"""
    doc.add_heading("参加者评价", 1)
    new_scores = result.get("参加者统计量")
    if new_scores is not None:
        rows = []
        formulas: set[str] = set()
        warnings: set[str] = set()
        for participant in data["participants"]:
            for name, score in new_scores.get(participant["id"], {}).items():
                rows.append(
                    [
                        participant["id"],
                        name,
                        _shown(score.get("value"), places=z_places),
                        score.get("status"),
                        score.get("classification") or "未评价",
                        score.get("reason") or "—",
                    ]
                )
                formulas.add(score.get("formula", ""))
                warnings.update(score.get("warnings", []))
        if rows:
            _table(doc, ["参加者", "统计量", "值", "状态", "评价", "原因"], rows)
            _table(
                doc,
                ["参加者", "测量值", "u(x)", "U(x)", "k", "数据来源"],
                [
                    [
                        p["id"],
                        _shown(p["value"]),
                        _shown(p.get("u")),
                        _shown(p.get("U")),
                        _shown(p.get("k")),
                        p.get("source", "未提供来源"),
                    ]
                    for p in data["participants"]
                ],
            )
        else:
            doc.add_paragraph("未提供参加者结果。")
        for formula in sorted(formulas):
            doc.add_paragraph(formula)
        for warning in sorted(warnings):
            doc.add_paragraph("提示：" + warning)
        return
    scores = result.get("参加者z", {})
    if scores:
        _table(
            doc,
            ["参加者", "结果", "z 值", "评价", "数据来源"],
            [
                [
                    p["id"],
                    _shown(p["value"]),
                    _shown(scores[p["id"]]["z"], places=z_places),
                    scores[p["id"]]["classification"],
                    p.get("source", "未提供来源"),
                ]
                for p in data["participants"]
                if p["id"] in scores
            ],
        )
    else:
        doc.add_paragraph("未提供可评价的指定值、标准差或参加者结果。")


def _project_methods(doc: Any, data: dict[str, Any], cfg: dict[str, Any]) -> None:
    """列出项目信息及各方法的条款。"""
    doc.add_heading("能力验证计算书", 0)
    doc.add_paragraph("计算结果供具备资质的人员复核使用。")
    doc.add_heading("项目信息", 1)
    _table(doc, ["项目", "内容"], [[k, _shown(v)] for k, v in data.get("info", {}).items()])
    doc.add_heading("方法与配置", 1)
    doc.add_paragraph(
        "判据比较采用相对容差 1e-12，容差内按相等处理；原始计算值未修约。"
        "严格小于的判据在相等时不通过，接近边界的结果应人工复核。"
    )
    method = (
        "单均值 t 检验：CNAS-GL003:2018 5.2.1"
        if cfg.get("stability_method") == "one_sample"
        else "两均值 t 检验：CNAS-GL003:2018 5.2.2"
    )
    _table(
        doc,
        ["项目", "选择与依据"],
        [
            ["均匀性方法", "单因子方差分析：CNAS-GL003:2018 4.2"],
            ["并列用途判据", "样品间标准差判据：CNAS-GL003:2018 4.3"],
            ["稳定性方法", method + "；均值差：5.3"],
            ["稳健统计方法", "算法 A：CNAS-GL002:2018 附录 A.2"],
            ["显著性水平", _shown(cfg.get("alpha", 0.05))],
            ["严格配置", "启用" if cfg.get("strict_homogeneity") else "未启用"],
        ],
    )


def _difference_table(doc: Any, differences: list[dict[str, Any]]) -> None:
    """只在正文列出有差异或需要提示的复核行。"""
    doc.add_heading("报告复核差异", 1)
    headers = [
        "统计量",
        "声称值",
        "报告模型",
        "推荐模型",
        "显示一致",
        "差异类型",
        "差异说明",
        "评分条目",
    ]
    for level, title in (("DIFFERENCE", "需核查的差异"), ("NOTE", "提示事项")):
        selected = [row for row in differences if row.get("状态") == level]
        doc.add_heading(title, 2)
        if not selected:
            doc.add_paragraph("无。")
            continue
        rows = []
        for row in selected:
            matches = row.get("显示一致")
            text = str(row.get("说明", ""))
            text = text.replace("repeats_pooled", "合并方差模型").replace(
                "repeats_welch", "非齐方差模型"
            )
            text = text.replace("df=", "自由度=").replace("s1=", "基线标准差=")
            digits = row.get("显示小数位")
            claim_places = digits if isinstance(digits, int) and 0 <= digits <= 12 else None
            design = row.get("差异类型") == "DESIGN_WARNING"
            not_applicable = "不适用（设计提示）"
            rows.append(
                [
                    row.get("统计量", ""),
                    not_applicable if design else _shown(row.get("声称值"), places=claim_places),
                    not_applicable if design else _shown(row.get("按报告模型复现值")),
                    not_applicable if design else _shown(row.get("按推荐模型重算值")),
                    not_applicable
                    if design
                    else "未评价（缺少数据）"
                    if matches is None
                    else "一致"
                    if matches
                    else "不一致",
                    row.get("差异类型", ""),
                    text,
                    row.get("评分条目", ""),
                ]
            )
        _table(doc, headers, rows)
    matches = sum(row.get("状态") == "MATCH" for row in differences)
    doc.add_heading("一致结果", 2)
    doc.add_paragraph(f"共 {matches} 项；完整逐项比较见差异清单。")


def _unevaluated(result: Any, path: str = "结果") -> list[tuple[str, str, str]]:
    """递归收集未评价或须设计审核的状态及已登记原因。"""
    rows: list[tuple[str, str, str]] = []
    if isinstance(result, dict):
        for key, value in result.items():
            current = f"{path}.{key}"
            if (key == "status" or key.endswith("_status")) and value in (
                "NOT_EVALUATED",
                "DESIGN_REVIEW",
                "UNASSESSED",
            ):
                reason = (
                    result.get("reason") or result.get("design_warnings") or result.get("warnings")
                )
                if isinstance(reason, list):
                    reason = "；".join(map(str, reason))
                if (
                    key in ("Ss_status", "mean_difference_status")
                    and value == "NOT_EVALUATED"
                    and result.get("status") != "DESIGN_REVIEW"
                ):
                    reason = "未提供用于用途判据的 σ"
                rows.append((current, str(value), str(reason or "结果未记录具体原因，需人工核查")))
            elif isinstance(value, str) and any(
                value.startswith(status + separator)
                for status in ("NOT_EVALUATED", "DESIGN_REVIEW", "UNASSESSED")
                for separator in ("：", ":")
            ):
                status, reason = value.replace("：", ":", 1).split(":", 1)
                rows.append((current, status, reason.strip() or "结果未记录具体原因，需人工核查"))
            elif isinstance(value, (dict, list)):
                rows.extend(_unevaluated(value, current))
    elif isinstance(result, list):
        for index, value in enumerate(result):
            rows.extend(_unevaluated(value, f"{path}[{index}]"))
    return rows


def make_report(
    path: str | Path,
    data: dict[str, Any],
    result: dict[str, Any],
    differences: list[dict[str, Any]] | None = None,
    input_sha256: str | None = None,
    decisions: list[dict[str, Any]] | None = None,
) -> None:
    """生成 GL003、GL002 计算书；附录保留未经修约的计算值。"""
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.left_margin, section.right_margin = Cm(1.5), Cm(1.5)
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    style.font.size = Pt(9)
    cfg = data.get("config", {})
    sig = int(cfg["display_sig_digits"]) if cfg.get("display_sig_digits") not in (None, "") else 4
    mean_places = (
        int(cfg["display_mean_decimals"])
        if cfg.get("display_mean_decimals") not in (None, "")
        else _data_places(data)
    )
    ss_places = (
        int(cfg["display_ss_decimals"]) if cfg.get("display_ss_decimals") not in (None, "") else 3
    )
    raw_z_places = cfg.get("display_z_decimals")
    z_places = int(raw_z_places) if raw_z_places not in (None, "") else 2
    if (
        isinstance(raw_z_places, bool)
        or (raw_z_places not in (None, "") and float(raw_z_places) != z_places)
        or not 1 <= sig <= 15
        or not 0 <= mean_places <= 12
        or not 0 <= ss_places <= 12
        or not 0 <= z_places <= 12
    ):
        raise ValueError("输出精度配置超出范围，z 小数位须为 0 至 12 的整数")
    _project_methods(doc, data, cfg)
    if data.get("batches"):
        doc.add_heading("候选批次追溯", 1)
        doc.add_paragraph("状态由用户登记，软件不选择批次；标准差为样本标准差。")
        fields = [
            "批次编号",
            "物品",
            "目标量值",
            "材质",
            "来源",
            "制备日期",
            "状态",
            "处理理由",
            "关联批次",
            "预实验结果",
            "预实验均值",
            "预实验标准差",
        ]
        _table(
            doc,
            fields,
            [
                [str(batch[field]) if batch.get(field) is not None else "" for field in fields]
                for batch in data["batches"]
            ],
        )
    doc.add_heading("原始数据", 1)
    _raw_tables(doc, data)
    if result.get("标准模式") == "gbt28043":
        _gbt_results(doc, result, cfg, sig)
    else:
        doc.add_paragraph("标准模式：gl003；GB/T 28043 扩展未作为主评价。")
    _homogeneity(doc, result, mean_places, sig, ss_places, float(cfg.get("alpha") or 0.05))
    _other_results(doc, data, result, sig, mean_places, z_places)
    if differences is not None:
        _difference_table(doc, differences)
    doc.add_heading("未评价事项", 1)
    unevaluated = _unevaluated(result)
    if unevaluated:
        _table(doc, ["条目", "状态", "原因"], [list(row) for row in unevaluated])
    else:
        doc.add_paragraph("结果中未发现上述未评价状态；未输入或未计算的事项仍需人工检查。")
    doc.add_heading("人工复核", 1)
    doc.add_paragraph("待人工复核；软件不自动放行，以下决定仅供人工复核。")
    latest = {str(item.get("item")): item for item in decisions or []}
    _table(
        doc,
        ["条目", "人工决定"],
        [
            [str(item), str(latest[item]["decision"]) if item in latest else "待人工复核"]
            for item in result
        ],
    )
    if decisions:
        _table(
            doc,
            ["时间（UTC）", "条目", "决定", "人员", "备注", "结果 SHA-256"],
            [
                [
                    item.get(key, "")
                    for key in ("time", "item", "decision", "by", "note", "result_sha256")
                ]
                for item in decisions
            ],
        )
    doc.add_paragraph("计算人：________________    日期：____________")
    doc.add_paragraph("复核人：________________    日期：____________")
    doc.add_page_break()
    doc.add_heading("附录：全精度记录", 1)
    doc.add_paragraph("软件版本：" + __version__)
    doc.add_paragraph("输入文件 SHA-256：" + (input_sha256 or "未提供"))
    doc.add_paragraph("生成时间（UTC）：" + datetime.now(timezone.utc).isoformat())
    doc.add_paragraph("配置原文：" + json.dumps(cfg, ensure_ascii=False, allow_nan=False))
    doc.add_paragraph("全精度结果：" + json.dumps(result, ensure_ascii=False, allow_nan=False))
    doc.save(str(path))
