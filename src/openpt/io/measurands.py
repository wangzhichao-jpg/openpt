# SPDX-License-Identifier: Apache-2.0
"""多被测量工作簿的只读隔离；不更改源文件及原始行号。"""

from io import BytesIO
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from ..errors import InputError

DATA_SHEETS = ("均匀性", "稳定性", "报告声称值")
CONFIG_FIELDS = {
    "单位",
    "sigma",
    "sigma_pt",
    "delta_e",
    "gbt_criterion_basis",
    "alpha",
    "stability_method",
    "baseline_source",
    "stability_design",
    "replicate_type",
    "criterion_standard",
    "gl003_hom_criterion",
    "report_gl003_hom_criterion",
    "gbt_hom_rule",
    "gbt_stability_rule",
    "reference",
    "reference_source",
    "reference_uncertainty_negligible",
    "observation_level",
    "sigma_source",
    "sigma_stage",
    "layout",
    "strict_homogeneity",
    "stability_u1",
    "stability_u2",
    "stability_period_options",
}


def _field_column(ws: Any, field: str) -> int | None:
    positions = [cell.column for cell in ws[1] if cell.value == field]
    if len(positions) > 1:
        raise InputError(f"{ws.title}!1：{field} 列重复")
    return positions[0] if positions else None


def _has_values(ws: Any, row: int, excluded: int | None) -> bool:
    return any(
        ws.cell(row, col).value not in (None, "")
        for col in range(1, ws.max_column + 1)
        if col != excluded
    )


def split_measurands(book: Any, mapping: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """返回每个被测量的内存工作簿及配置来源；空列表表示普通单量工作簿。"""
    mapping = mapping or {}
    names: list[str] = []
    for sheet in DATA_SHEETS:
        if sheet not in book.sheetnames:
            continue
        ws = book[sheet]
        col = _field_column(ws, "被测量")
        if col is None:
            continue
        for row in range(2, ws.max_row + 1):
            cell = ws.cell(row, col)
            if cell.data_type == "f":
                raise InputError(f"{sheet}!{cell.coordinate}: 被测量不接受公式")
            if cell.value not in (None, ""):
                if not isinstance(cell.value, str) or not cell.value.strip():
                    raise InputError(f"{sheet}!{cell.coordinate}: 被测量须为非空文字")
                name = cell.value.strip()
                if name not in names:
                    names.append(name)
    if not names:
        if "被测量配置" in book.sheetnames:
            ws = book["被测量配置"]
            if any(_has_values(ws, row, None) for row in range(2, ws.max_row + 1)):
                raise InputError("被测量配置：数据表中未登记任何被测量")
        return []
    for sheet in DATA_SHEETS:
        if sheet not in book.sheetnames:
            continue
        ws = book[sheet]
        col = _field_column(ws, "被测量")
        for row in range(2, ws.max_row + 1):
            if not _has_values(ws, row, col):
                continue
            if col is None and len(names) > 1:
                raise InputError(f"{sheet}!A{row}: 多被测量数据须指定被测量")
            if col is not None and ws.cell(row, col).value in (None, ""):
                raise InputError(f"{sheet}!{ws.cell(row, col).coordinate}: 被测量缺失")
    if len(names) > 1 and "参加者结果" in book.sheetnames:
        ws = book["参加者结果"]
        if any(_has_values(ws, row, None) for row in range(2, ws.max_row + 1)):
            raise InputError("多被测量时参加者结果尚不支持分别归属，不能混用")
    options: dict[str, dict[str, Any]] = {name: {} for name in names}
    option_sources: dict[str, dict[str, str]] = {name: {} for name in names}
    if "被测量配置" in book.sheetnames:
        ws = book["被测量配置"]
        columns = [_field_column(ws, field) for field in ("被测量", "字段", "值")]
        if any(col is None for col in columns):
            raise InputError("被测量配置!1：需要被测量、字段、值列")
        name_col, key_col, value_col = columns
        for row in range(2, ws.max_row + 1):
            if not _has_values(ws, row, None):
                continue
            cells = [ws.cell(row, col) for col in (name_col, key_col, value_col)]
            if any(cell.data_type == "f" for cell in cells):
                raise InputError(f"被测量配置!A{row}: 不接受公式")
            raw_name, key, value = (cell.value for cell in cells)
            name = raw_name.strip() if isinstance(raw_name, str) else raw_name
            if name not in options or key not in CONFIG_FIELDS or value in (None, ""):
                raise InputError(f"被测量配置!A{row}: 被测量、字段或值无效")
            if key in options[name]:
                raise InputError(f"被测量配置!{cells[1].coordinate}: 被测量配置字段重复")
            options[name][key] = value
            option_sources[name][key] = f"被测量配置!{cells[2].coordinate}"
    raw = BytesIO()
    book.save(raw)
    payload = raw.getvalue()
    separated = []
    for name in names:
        clone = load_workbook(BytesIO(payload), data_only=False)
        for sheet in DATA_SHEETS:
            if sheet not in clone.sheetnames:
                continue
            ws = clone[sheet]
            col = _field_column(ws, "被测量")
            if col is None:
                continue
            for row in range(2, ws.max_row + 1):
                cell = ws.cell(row, col)
                current = cell.value.strip() if isinstance(cell.value, str) else cell.value
                if current not in (None, "", name):
                    for item in ws[row]:
                        item.value = None
                else:
                    cell.value = None
            ws.cell(1, col).value = None
        if "被测量配置" in clone.sheetnames:
            del clone["被测量配置"]
        unit = options[name].get("单位")
        if unit is not None:
            if "项目信息" not in clone.sheetnames:
                raise InputError("缺少工作表：项目信息")
            if not isinstance(unit, str) or not unit.strip():
                raise InputError(f"{option_sources[name]['单位']}: 单位须为非空文字")
            ws = clone["项目信息"]
            aliases = mapping.get("项目信息", {})
            key_col = _field_column(ws, aliases.get("字段", "字段"))
            value_col = _field_column(ws, aliases.get("值", "值"))
            if key_col is None or value_col is None:
                raise InputError("项目信息：列映射无效")
            found = False
            for row in range(2, ws.max_row + 1):
                if ws.cell(row, key_col).value == "单位":
                    ws.cell(row, value_col).value = unit
                    found = True
                    break
            if not found:
                raise InputError("项目信息：缺少单位字段")
        appended = {}
        if options[name]:
            if "方法配置" not in clone.sheetnames:
                clone.create_sheet("方法配置").append(["字段", "值"])
            ws = clone["方法配置"]
            aliases = mapping.get("方法配置", {})
            key_col = _field_column(ws, aliases.get("字段", "字段"))
            value_col = _field_column(ws, aliases.get("值", "值"))
            if key_col is None or value_col is None:
                raise InputError("方法配置：列映射无效")
            for key, value in options[name].items():
                if key == "单位":
                    continue
                row = ws.max_row + 1
                ws.cell(row, key_col, key)
                ws.cell(row, value_col, value)
                appended[f"方法配置!{get_column_letter(value_col)}{row}"] = option_sources[name][
                    key
                ]
        output = BytesIO()
        clone.save(output)
        clone.close()
        separated.append({"name": name, "bytes": output.getvalue(), "sources": appended})
    return separated
