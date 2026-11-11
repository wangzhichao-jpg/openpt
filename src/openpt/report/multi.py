# SPDX-License-Identifier: Apache-2.0
"""从同一 DOCX 内容导出 XLSX 和自包含 HTML。"""

import html
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from openpyxl import Workbook


def _numbers(value: Any, path: str = "结果") -> Iterator[tuple[str, int | float]]:
    """递归提取有限数值路径，保留未修约值。"""
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _numbers(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _numbers(item, f"{path}[{index}]")


def _text(cell: Any, value: Any) -> None:
    """所有文本强制标记为字符串，防止 Excel 公式注入。"""
    if isinstance(value, str):
        cell.value = value
        cell.data_type = "s"
    else:
        cell.value = value


def _sheet(book: Any, title: str) -> Any:
    """生成合法且不重复的工作表名称。"""
    base = re.sub(r"[\\/*?:\[\]]", "_", title).strip("'")[:25] or "内容"
    name = base
    index = 1
    while name.casefold() in {item.casefold() for item in book.sheetnames}:
        name = f"{base[:25]}_{index}"
        index += 1
    sheet = book.create_sheet(name)
    sheet.freeze_panes = "A2"
    return sheet


def export_reports(
    docx_path: str | Path, xlsx_path: str | Path, html_path: str | Path, result: dict[str, Any]
) -> None:
    """使用 DOCX 段落和表格作为共享内容，附未修约数值表。"""
    doc = Document(str(docx_path))
    book = Workbook()
    book.remove(book.active)
    sheet = _sheet(book, "计算书")
    output = [
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
        "<style>body{font-family:sans-serif;margin:2em}table{border-collapse:collapse}",
        "td,th{border:1px solid #555;padding:.3em}@media print{body{margin:0}}</style>",
        "</head><body>",
    ]
    for child in doc.element.body:
        if isinstance(child, CT_P):
            paragraph = Paragraph(child, doc)
            text = paragraph.text
            if paragraph.style and paragraph.style.name.startswith("Heading"):
                sheet = _sheet(book, text)
                output.append(f"<h2>{html.escape(text)}</h2>")
            else:
                output.append(f"<p>{html.escape(text)}</p>")
            # Excel 单元格最多 32767 字符；长文本分块保留。
            for start in range(0, max(1, len(text)), 32000):
                _text(sheet.cell(sheet.max_row + 1, 1), text[start : start + 32000])
        elif isinstance(child, CT_Tbl):
            table = Table(child, doc)
            output.append("<table>")
            for row in table.rows:
                output.append("<tr>")
                row_number = sheet.max_row + 1
                for col, cell in enumerate(row.cells, 1):
                    text = cell.text
                    _text(sheet.cell(row_number, col), text)
                    output.append(f"<td>{html.escape(text)}</td>")
                output.append("</tr>")
            output.append("</table>")
    sheet = _sheet(book, "全精度数值")
    sheet.append(["字段", "原始数值", "修约显示", "原始精度文本"])
    output.append(
        "<h2>全精度数值</h2><table><tr><th>字段</th><th>原始数值</th>"
        "<th>修约显示</th><th>原始精度文本</th></tr>"
    )
    for path, number in _numbers(result):
        shown = str(number) if isinstance(number, int) else f"{number:.4g}"
        exact = json.dumps(number, allow_nan=False)
        row = sheet.max_row + 1
        for col, item in enumerate((path, number, shown, exact), 1):
            _text(sheet.cell(row, col), item)
        values = (path, exact, shown, exact)
        output.append("<tr>" + "".join(f"<td>{html.escape(v)}</td>" for v in values) + "</tr>")
    output.append("</table></body></html>")
    for ws in book:
        ws.column_dimensions["A"].width = 50
        for column in ("B", "C", "D"):
            ws.column_dimensions[column].width = 25
    book.save(xlsx_path)
    Path(html_path).write_text("\n".join(output), encoding="utf-8")
