# SPDX-License-Identifier: Apache-2.0
"""多工作簿复核及可筛选差异总表。"""

from pathlib import Path
from typing import Any

from openpyxl import Workbook

from ..cli import calculate
from ..io.excel import read_workbook
from .compare import review


def batch_review(
    paths: list[str | Path], mapping: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """逐个输入重算、复核，按差异等级分组且保留项目和文件来源。"""
    if not paths:
        raise ValueError("至少提供一个输入工作簿")
    rows = []
    for path in paths:
        data = read_workbook(path)
        for row in review(data, calculate(data), mapping):
            rows.append({"项目": data["info"]["项目名称"], "输入文件": str(path), **row})
    priority = {"DIFFERENCE": 0, "NOTE": 1, "MATCH": 2}
    return sorted(rows, key=lambda row: priority[row["状态"]])


def write_xlsx(path: str | Path, rows: list[dict[str, Any]]) -> None:
    """输出可筛选的 XLSX 总表；文本按文本写入以阻止公式注入。"""
    fields = [
        "状态",
        "项目",
        "输入文件",
        "统计量",
        "声称值",
        "来源",
        "显示小数位",
        "按报告模型复现值",
        "按推荐模型重算值",
        "按报告显示值",
        "按推荐显示值",
        "显示一致",
        "推荐一致",
        "差异类型",
        "评分条目",
        "说明",
    ]
    book = Workbook()
    ws = book.active
    ws.title = "差异总表"
    ws.append(fields)
    for row in rows:
        for col, field in enumerate(fields, 1):
            value = row.get(field)
            cell = ws.cell(ws.max_row + 1 if col == 1 else ws.max_row, col, value)
            if isinstance(value, str):
                cell.data_type = "s"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for column in ws.columns:
        ws.column_dimensions[column[0].column_letter].width = 20
    book.save(path)
