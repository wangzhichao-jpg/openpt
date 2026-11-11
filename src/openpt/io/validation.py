# SPDX-License-Identifier: Apache-2.0
"""只读检查 Excel 或 CSV 测量表；问题不改变原始数据。"""

import csv
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from ..errors import InputError
from .excel import SHEETS

MEASUREMENT_SHEETS = ("均匀性", "稳定性", "参加者结果")


@dataclass(frozen=True)
class Issue:
    """导入问题及其原始位置和单元格内容。"""

    category: str
    sheet: str
    cell: str
    original: Any
    message: str

    def to_dict(self) -> dict[str, Any]:
        """返回可序列化的问题记录。"""
        return asdict(self)


def _positions(headers: list[Any], sheet: str, mapping: dict[str, Any]) -> dict[str, int]:
    """解析标准字段到原始列名的映射；拒绝缺失和重复列名。"""
    aliases = mapping.get(sheet, {})
    if not isinstance(aliases, dict):
        raise InputError(f"{sheet} 的列映射必须是对象")
    required = SHEETS[sheet]
    if set(aliases) - set(required):
        raise InputError(f"{sheet} 的列映射包含未知标准字段")
    positions = {}
    for field in required:
        name = aliases.get(field, field)
        if not isinstance(name, str) or headers.count(name) != 1:
            raise InputError(f"{sheet}：列 {name!r} 不存在或不唯一")
        positions[field] = headers.index(name)
    if len(set(positions.values())) != len(positions):
        raise InputError(f"{sheet}：多个标准字段映射到同一列")
    return positions


def _check_rows(
    sheet: str,
    rows: list[list[Any]],
    cached: list[list[Any]],
    mapping: dict[str, Any],
    *,
    csv_numbers: bool = False,
    formulas: set[str] | None = None,
) -> list[Issue]:
    """检查缺失、单位、编号、非数值和没有缓存的公式。"""
    if not rows:
        raise InputError(f"{sheet}：缺少表头")
    positions = _positions(rows[0], sheet, mapping)
    issues: list[Issue] = []
    seen: set[tuple[str, ...]] = set()
    unit: Any = None
    numeric = "值"
    formulas = formulas or set()
    keys = {
        "均匀性": ("单元编号", "重复编号"),
        "稳定性": ("时间组", "单元编号", "重复编号"),
        "参加者结果": ("参加者编号",),
    }[sheet]
    for index, row in enumerate(rows[1:], 2):

        def value(field: str, current_row: list[Any] = row) -> Any:
            col = positions[field]
            return current_row[col] if col < len(current_row) else None

        if not any(item not in (None, "") for item in row):
            continue

        def add(category: str, field: str, message: str, row_number: int = index) -> None:
            col = positions[field]
            issues.append(
                Issue(
                    category,
                    sheet,
                    f"{get_column_letter(col + 1)}{row_number}",
                    value(field),
                    message,
                )
            )

        for field in SHEETS[sheet]:
            raw = value(field)
            if raw in (None, ""):
                add("MISSING", field, "必填值缺失")
            elif f"{get_column_letter(positions[field] + 1)}{index}" in formulas:
                col = positions[field]
                cache_row = cached[index - 1] if index - 1 < len(cached) else []
                if col >= len(cache_row) or cache_row[col] is None:
                    add("FORMULA_NO_CACHE", field, "公式没有缓存值")
                else:
                    add("FORMULA", field, "现有计算器不接受公式")
        raw = value(numeric)
        is_formula = f"{get_column_letter(positions[numeric] + 1)}{index}" in formulas
        if raw not in (None, "") and not is_formula:
            try:
                number = float(raw) if csv_numbers and isinstance(raw, str) else raw
                valid = (
                    not isinstance(number, bool)
                    and isinstance(number, (int, float))
                    and math.isfinite(number)
                )
            except (ValueError, OverflowError):
                valid = False
            if not valid:
                add("NON_NUMERIC", numeric, "数值必须为有限数")
        actual = value("单位")
        if actual not in (None, ""):
            if unit is None:
                unit = actual
            elif actual != unit:
                add("UNIT_MISMATCH", "单位", "同一测量表单位不一致")
        identifier = tuple(str(value(k)) for k in keys)
        if all(value(k) not in (None, "") for k in keys):
            if identifier in seen:
                add("DUPLICATE", keys[-1], "编号组合重复")
            seen.add(identifier)
    return issues


def inspect_input(
    path: str | Path,
    mapping: dict[str, Any] | None = None,
    *,
    encoding: str = "utf-8-sig",
    csv_sheet: str = "均匀性",
) -> list[Issue]:
    """只读检查测量表；CSV 按显式编码严格解码，默认兼容 UTF-8 BOM。"""
    source = Path(path)
    mapping = mapping or {}
    if source.suffix.lower() == ".csv":
        if csv_sheet not in MEASUREMENT_SHEETS:
            raise InputError("CSV 工作表类型无效")
        try:
            with source.open("r", encoding=encoding, errors="strict", newline="") as stream:
                rows = list(csv.reader(stream))
        except (UnicodeDecodeError, LookupError) as exc:
            raise InputError("CSV 编码错误；若文件为 GBK，请显式指定 --encoding gbk") from exc
        return _check_rows(csv_sheet, rows, [], mapping, csv_numbers=True)
    if source.suffix.lower() != ".xlsx":
        raise InputError("只支持 XLSX 或 CSV")
    book = load_workbook(source, data_only=False, read_only=True)
    values = load_workbook(source, data_only=True, read_only=True)
    try:
        issues: list[Issue] = []
        project_unit: Any = None
        if "项目信息" in book.sheetnames:
            for row in book["项目信息"].iter_rows(min_row=2, values_only=True):
                if len(row) >= 2 and row[0] == "单位" and row[1] not in (None, ""):
                    project_unit = row[1]
                    break
        if not set(MEASUREMENT_SHEETS).intersection(book.sheetnames):
            raise InputError("缺少可检查的测量工作表")
        for sheet in MEASUREMENT_SHEETS:
            if sheet not in book.sheetnames:
                continue
            cells = list(book[sheet].iter_rows())
            rows = [[cell.value for cell in row] for row in cells]
            formulas = {cell.coordinate for row in cells for cell in row if cell.data_type == "f"}
            cached = [list(row) for row in values[sheet].iter_rows(values_only=True)]
            issues.extend(_check_rows(sheet, rows, cached, mapping, formulas=formulas))
            if rows:
                position = _positions(rows[0], sheet, mapping)["单位"]
                for index, row in enumerate(rows[1:], 2):
                    value = row[position] if position < len(row) else None
                    if value in (None, ""):
                        continue
                    if project_unit is None:
                        project_unit = value
                    elif value != project_unit:
                        cell = f"{get_column_letter(position + 1)}{index}"
                        if not any(
                            i.category == "UNIT_MISMATCH" and i.sheet == sheet and i.cell == cell
                            for i in issues
                        ):
                            issues.append(
                                Issue(
                                    "UNIT_MISMATCH",
                                    sheet,
                                    cell,
                                    value,
                                    "单位与项目或其他测量表不一致",
                                )
                            )
        return issues
    finally:
        book.close()
        values.close()
