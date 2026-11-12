# SPDX-License-Identifier: Apache-2.0
"""只读检查 Excel 或 CSV 测量表；问题不改变原始数据。"""

import csv
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from ..errors import InputError
from .excel import PARTICIPANT_OPTIONAL, SHEETS

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
    if sheet == "报告声称值" and len(headers) >= 6 and headers[5] is None:
        headers = [*headers[:5], "时间组", *headers[6:]]
    allowed = set(required) | (set(PARTICIPANT_OPTIONAL) if sheet == "参加者结果" else set())
    if set(aliases) - allowed:
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


def _check_numeric_table(
    sheet: str, rows: list[list[Any]], mapping: dict[str, Any], formulas: set[str]
) -> list[Issue]:
    """检查声称值与算法 S 的必填项和数值原文。"""
    if not rows:
        return []
    header = rows[0] + [None] * max(0, len(SHEETS[sheet]) - len(rows[0]))
    positions = _positions(header, sheet, mapping)
    required = ("统计量", "声称值", "来源") if sheet == "报告声称值" else tuple(SHEETS[sheet])
    numeric = ("声称值", "显示小数位") if sheet == "报告声称值" else tuple(SHEETS[sheet])
    issues = []
    for number, row in enumerate(rows[1:], 2):
        if not any(value not in (None, "") for value in row):
            continue
        for field in dict.fromkeys((*required, *numeric)):
            column = positions[field]
            value = row[column] if column < len(row) else None
            cell = f"{get_column_letter(column + 1)}{number}"
            if value in (None, ""):
                if field in required:
                    issues.append(Issue("MISSING", sheet, cell, value, "必填值缺失"))
            elif field in numeric and cell not in formulas:
                try:
                    valid = (
                        not isinstance(value, bool)
                        and isinstance(value, (int, float))
                        and math.isfinite(value)
                    )
                except OverflowError:
                    valid = False
                if not valid:
                    issues.append(Issue("NON_NUMERIC", sheet, cell, value, "数值必须为有限数"))
    return issues


def _check_numeric_config(
    sheet: str, rows: list[list[Any]], mapping: dict[str, Any], formulas: set[str]
) -> list[Issue]:
    """检查方法及定值配置中明确要求为数值的字段。"""
    if not rows:
        return []
    positions = _positions(rows[0], sheet, mapping)
    known = {
        "alpha",
        "sigma",
        "reference",
        "assigned",
        "sigma_pt",
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
        "value",
        "uncertainty",
        "sigma_temporary",
        "sigma_final",
        "u_hom",
        "u_stab",
        "U_assigned",
        "k_assigned",
    }
    issues = []
    for number, row in enumerate(rows[1:], 2):
        key_col, value_col = positions["字段"], positions["值"]
        key = row[key_col] if key_col < len(row) else None
        value = row[value_col] if value_col < len(row) else None
        match = re.search(r"（([a-zA-Z_][a-zA-Z_0-9]*)）$", str(key))
        field = match.group(1) if match else str(key)
        cell = f"{get_column_letter(value_col + 1)}{number}"
        if field not in known or value in (None, "") or cell in formulas:
            continue
        try:
            valid = (
                not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(value)
            )
        except OverflowError:
            valid = False
        if not valid:
            issues.append(Issue("NON_NUMERIC", sheet, cell, value, "配置值必须为有限数"))
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
        for sheet in sorted(set(book.sheetnames) - set(MEASUREMENT_SHEETS) - {"填写说明"}):
            if sheet in ("报告声称值", "算法S", "方法配置", "指定值与不确定度"):
                cells = list(book[sheet].iter_rows())
                rows = [[cell.value for cell in row] for row in cells]
                formulas = {
                    cell.coordinate for row in cells for cell in row if cell.data_type == "f"
                }
                if sheet in ("报告声称值", "算法S"):
                    issues.extend(_check_numeric_table(sheet, rows, mapping, formulas))
                else:
                    issues.extend(_check_numeric_config(sheet, rows, mapping, formulas))
            for row in book[sheet].iter_rows():
                for cell in row:
                    if cell.data_type != "f":
                        continue
                    cached = values[sheet][cell.coordinate].value
                    category = "FORMULA_NO_CACHE" if cached is None else "FORMULA"
                    message = "公式没有缓存值" if cached is None else "现有计算器不接受公式"
                    issues.append(Issue(category, sheet, cell.coordinate, cell.value, message))
        return issues
    finally:
        book.close()
        values.close()
