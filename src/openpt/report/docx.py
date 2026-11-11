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


def _shown(value: Any, digits: int = 4, places: int | None = None) -> str:
    """输出指定精度，空值和布尔值使用中文。"""
    if value is None:
        return "未评价"
    if isinstance(value, bool):
        return "通过" if value else "不通过"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{places}f}" if places is not None else f"{value:.{digits}g}"
    return str(value)


def _table(doc: Any, headers: list[str], rows: list[list[Any]]) -> None:
    """创建带底纹和重复表头的可跨页表格。"""
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    header = table.rows[0]
    trpr = header._tr.get_or_add_trPr()
    repeat = OxmlElement("w:tblHeader")
    repeat.set(qn("w:val"), "true")
    trpr.append(repeat)
    for cell, title in zip(header.cells, headers, strict=True):
        cell.text = title
        tcpr = cell._tc.get_or_add_tcPr()
        shade = OxmlElement("w:shd")
        shade.set(qn("w:fill"), "D9EAF7")
        tcpr.append(shade)
    for values in rows:
        cells = table.add_row().cells
        for cell, value in zip(cells, values, strict=True):
            cell.text = str(value)
            if isinstance(value, (int, float)) or (
                isinstance(value, str) and value.lstrip("-+").replace(".", "", 1).isdigit()
            ):
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT


def _data_places(data: dict[str, Any]) -> int:
    """以已导入数字的十进制表示估计原始小数位。"""
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


def _raw_tables(doc: Any, data: dict[str, Any]) -> None:
    """按单元和重复次数显示均匀性与稳定性原始值。"""
    blocks = [("均匀性", data.get("homogeneity", []))]
    blocks.extend((f"稳定性：{key}", value) for key, value in data.get("stability", {}).items())
    sources = data.get("sources", [])
    for name, groups in blocks:
        if not groups:
            continue
        doc.add_paragraph(name)
        count = max(len(group) for group in groups)
        headers = ["单元顺序"] + [f"重复 {i}" for i in range(1, count + 1)]
        _table(doc, headers, [[i, *map(str, row)] for i, row in enumerate(groups, 1)])
    if sources:
        doc.add_paragraph("数据来源：" + "、".join(sources))
    else:
        doc.add_paragraph("未提供原始测量值。")


def _homogeneity(
    doc: Any, result: dict[str, Any], mean_places: int, sig: int, ss_places: int
) -> None:
    """按 GL003 4.2、4.3 显示方差分析和用途判据。"""
    h = result.get("均匀性")
    doc.add_heading("均匀性方差分析", 1)
    if not h:
        doc.add_paragraph("未提供均匀性数据。")
        return
    _table(
        doc,
        ["变异来源", "自由度", "平方和", "均方"],
        [
            ["样品间", h["df_between"], _shown(h["SS_between"]), _shown(h["MS_between"])],
            ["样品内", h["df_within"], _shown(h["SS_within"]), _shown(h["MS_within"])],
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
            ["用途判据限值", _shown(h["threshold"], places=ss_places)],
        ],
    )
    doc.add_paragraph("选定方法结论：" + _shown(h["conclusion"]))
    doc.add_paragraph("并列提示：样品间标准差判据" + _shown(h["Ss_pass"]))
    doc.add_paragraph("计算状态：" + str(h["status"]))
    for warning in h.get("design_warnings", []) + h.get("warnings", []):
        doc.add_paragraph("提示：" + warning)


def _other_results(doc: Any, data: dict[str, Any], result: dict[str, Any], sig: int) -> None:
    """显示稳定性、稳健统计和参加者评价。"""
    doc.add_heading("稳定性评价", 1)
    s = result.get("稳定性")
    if s:
        names = [
            ("均值差", "difference"),
            ("t 值", "t"),
            ("自由度", "df"),
            ("t 临界值", "critical"),
            ("p 值", "p"),
            ("t 检验结论", "pass"),
            ("均值差判据", "mean_difference_pass"),
        ]
        _table(doc, ["项目", "结果"], [[label, _shown(s.get(key), sig)] for label, key in names])
        doc.add_paragraph("计算状态：" + str(s.get("status", "未评价")))
        for warning in s.get("design_warnings", []):
            doc.add_paragraph("设计提示：" + warning)
    else:
        doc.add_paragraph("未提供稳定性数据。")
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
        _table(doc, ["项目", "结果"], [[label, _shown(a.get(key), sig)] for label, key in names])
        rules = {"gl002": "GL002 第三有效位规则", "absolute": "绝对容差", "simplified": "简化法"}
        doc.add_paragraph("停止规则：" + rules.get(a.get("rule"), "未提供"))
    else:
        doc.add_paragraph("未提供参加者结果。")
    doc.add_heading("参加者评价", 1)
    scores = result.get("参加者z", {})
    if scores:
        _table(
            doc,
            ["参加者", "结果", "z 值", "评价"],
            [
                [
                    p["id"],
                    _shown(p["value"]),
                    _shown(scores[p["id"]]["z"], sig),
                    scores[p["id"]]["classification"],
                ]
                for p in data["participants"]
                if p["id"] in scores
            ],
        )
    else:
        doc.add_paragraph("未提供可评价的指定值、标准差或参加者结果。")


def make_report(
    path: str | Path,
    data: dict[str, Any],
    result: dict[str, Any],
    differences: list[dict[str, Any]] | None = None,
    input_sha256: str | None = None,
) -> None:
    """生成 GL003、GL002 计算书；附录保留未经修约的计算值。"""
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    style.font.size = Pt(9)
    cfg = data.get("config", {})
    sig = int(cfg.get("display_sig_digits") or 4)
    mean_places = int(cfg.get("display_mean_decimals") or _data_places(data))
    ss_places = int(cfg.get("display_ss_decimals") or 3)
    doc.add_heading("能力验证计算书", 0)
    doc.add_paragraph("计算结果供具备资质的人员复核使用。")
    doc.add_heading("项目信息", 1)
    _table(doc, ["项目", "内容"], [[k, _shown(v)] for k, v in data.get("info", {}).items()])
    doc.add_heading("方法与配置", 1)
    _table(
        doc,
        ["项目", "选择与依据"],
        [
            ["均匀性方法", "单因子方差分析：CNAS-GL003:2018 4.2"],
            ["并列用途判据", "样品间标准差判据：CNAS-GL003:2018 4.3"],
            ["稳定性方法", "t 检验及均值差：CNAS-GL003:2018 5.2、5.3"],
            ["稳健统计方法", "算法 A：CNAS-GL002:2018 附录 A.2"],
            ["显著性水平", _shown(cfg.get("alpha", 0.05))],
            ["严格配置", "启用" if cfg.get("strict_homogeneity") else "未启用"],
        ],
    )
    doc.add_heading("原始数据", 1)
    _raw_tables(doc, data)
    _homogeneity(doc, result, mean_places, sig, ss_places)
    _other_results(doc, data, result, sig)
    if differences is not None:
        doc.add_heading("报告复核差异", 1)
        headers = ["统计量", "声称值", "报告模型", "推荐模型", "显示一致", "差异说明", "评分条目"]
        rows = [
            [
                r.get("统计量", ""),
                _shown(r.get("声称值")),
                _shown(r.get("按报告模型复现值")),
                _shown(r.get("按推荐模型重算值")),
                _shown(r.get("显示一致")),
                (str(r.get("差异类型", "")) + " " + str(r.get("说明", "")))
                .replace("repeats_pooled", "合并方差模型")
                .replace("repeats_welch", "非齐方差模型")
                .replace("df=", "自由度=")
                .replace("s1=", "基线标准差="),
                r.get("评分条目", ""),
            ]
            for r in differences
        ]
        _table(doc, headers, rows)
    doc.add_heading("人工复核", 1)
    doc.add_paragraph("计算人：________________    日期：____________")
    doc.add_paragraph("复核人：________________    日期：____________")
    doc.add_page_break()
    doc.add_heading("附录：全精度记录", 1)
    doc.add_paragraph("软件版本：0.0.1")
    doc.add_paragraph("输入文件 SHA-256：" + (input_sha256 or "未提供"))
    doc.add_paragraph("生成时间（UTC）：" + datetime.now(timezone.utc).isoformat())
    doc.add_paragraph("配置原文：" + json.dumps(cfg, ensure_ascii=False, allow_nan=False))
    doc.add_paragraph("全精度结果：" + json.dumps(result, ensure_ascii=False, allow_nan=False))
    doc.save(str(path))
