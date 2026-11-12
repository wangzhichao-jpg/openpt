# SPDX-License-Identifier: Apache-2.0
"""只读检查 Excel 或 CSV 测量表；问题不改变原始数据。"""

import csv
import math
import re
from dataclasses import asdict, dataclass, replace
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.cell import column_index_from_string, coordinate_from_string, get_column_letter

from ..config.catalog import ENUMS
from ..core.gbt28043 import period_options as gbt_period_options
from ..errors import InputError
from .excel import PARTICIPANT_OPTIONAL, SHEETS
from .layout import wide_to_long
from .measurands import DATA_SHEETS, split_measurands
from .shape import (
    STABILITY_METHOD_ALIASES,
    insufficient_homogeneity_replicates,
    insufficient_units,
    stability_structure_problem,
)

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
    if sheet == "参加者结果":
        for field in PARTICIPANT_OPTIONAL:
            name = aliases.get(field, field)
            if name not in headers and field not in aliases:
                continue
            if not isinstance(name, str) or headers.count(name) != 1:
                raise InputError(f"{sheet}：可选列 {name!r} 不存在或不唯一")
            index = headers.index(name)
            if index in positions.values():
                raise InputError(f"{sheet}：多个标准字段映射到同一列")
            positions[field] = index
    return positions


def _restore_origin(issue: Issue, origins: dict[str, str], rows: list[list[Any]]) -> Issue:
    """将虚拟长表的问题映回原地址及该单元格原始内容。"""
    address = origins.get(issue.cell)
    if address is None:
        return issue
    letter, number = coordinate_from_string(address)
    index = column_index_from_string(letter) - 1
    row = rows[number - 1] if number <= len(rows) else []
    return replace(issue, cell=address, original=row[index] if index < len(row) else None)


def _unsupported_measurand(sheet: str, rows: list[list[Any]]) -> list[Issue]:
    """在尚未实现分被测量计算时拒绝混合结果。"""
    if not rows or "被测量" not in rows[0]:
        return []
    positions = [i for i, value in enumerate(rows[0]) if value == "被测量"]
    return [
        Issue(
            "UNSUPPORTED_MEASURAND",
            sheet,
            f"{get_column_letter(column + 1)}{index}",
            row[column],
            "当前版本尚不能按被测量分别计算，拒绝混合数据",
        )
        for index, row in enumerate(rows[1:], 2)
        for column in positions
        if column < len(row) and row[column] not in (None, "")
    ]


def _check_rows(
    sheet: str,
    rows: list[list[Any]],
    cached: list[list[Any]],
    mapping: dict[str, Any],
    *,
    csv_numbers: bool = False,
    formulas: set[str] | None = None,
    replicate_type: str = "technical",
    standard: str = "gl003",
) -> list[Issue]:
    """检查缺失、单位、编号、非数值和没有缓存的公式。"""
    if not rows:
        raise InputError(f"{sheet}：缺少表头")
    positions = _positions(rows[0], sheet, mapping)
    issues: list[Issue] = []
    seen: set[tuple[str, ...]] = set()
    homogeneity_units: dict[str, tuple[set[str], int, Any]] = {}
    stability_units: dict[str, dict[str, tuple[set[str], int, Any]]] = {}
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
        if sheet == "参加者结果":
            for field in PARTICIPANT_OPTIONAL:
                if field not in positions:
                    continue
                raw_optional = value(field)
                if raw_optional in (None, ""):
                    continue
                address = f"{get_column_letter(positions[field] + 1)}{index}"
                if address in formulas:
                    col = positions[field]
                    cache_row = cached[index - 1] if index - 1 < len(cached) else []
                    category = (
                        "FORMULA_NO_CACHE"
                        if col >= len(cache_row) or cache_row[col] is None
                        else "FORMULA"
                    )
                    add(
                        category,
                        field,
                        "公式没有缓存值"
                        if category == "FORMULA_NO_CACHE"
                        else "现有计算器不接受公式",
                    )
                    continue
                try:
                    number = (
                        float(raw_optional)
                        if csv_numbers and isinstance(raw_optional, str)
                        else raw_optional
                    )
                    valid = (
                        not isinstance(number, bool)
                        and isinstance(number, (int, float))
                        and math.isfinite(number)
                    )
                except (ValueError, OverflowError):
                    valid = False
                if not valid:
                    add("NON_NUMERIC", field, "数值必须为有限数")
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
        if sheet == "均匀性" and value("单元编号") not in (None, ""):
            uid = str(value("单元编号"))
            repeats, _, _ = homogeneity_units.setdefault(uid, (set(), index, value("值")))
            if value("重复编号") not in (None, ""):
                repeats.add(str(value("重复编号")))
        if (
            sheet == "稳定性"
            and value("时间组") not in (None, "")
            and value("单元编号") not in (None, "")
        ):
            group = stability_units.setdefault(str(value("时间组")), {})
            repeats, _, _ = group.setdefault(str(value("单元编号")), (set(), index, value("值")))
            if value("重复编号") not in (None, ""):
                repeats.add(str(value("重复编号")))
    for uid, (repeats, row_number, original) in homogeneity_units.items():
        bad_single = replicate_type == "single" and len(repeats) != 1
        bad_repeats = replicate_type != "single" and insufficient_homogeneity_replicates(
            len(repeats)
        )
        if bad_single or bad_repeats:
            cell = f"{get_column_letter(positions['值'] + 1)}{row_number}"
            message = (
                f"单元 {uid} 单测设计须恰好测量一次"
                if bad_single
                else f"单元 {uid} 至少需要两次重复"
            )
            issues.append(Issue("INSUFFICIENT_REPLICATES", sheet, cell, original, message))
    groups = {"均匀性": homogeneity_units} if homogeneity_units else {}
    groups.update(stability_units)
    for name, group in groups.items():
        if insufficient_units(len(group)):
            _, row_number, original = next(iter(group.values()))
            cell = f"{get_column_letter(positions['值'] + 1)}{row_number}"
            issues.append(
                Issue("INSUFFICIENT_SAMPLES", sheet, cell, original, f"{name}至少需要两个单元")
            )
        if (
            sheet == "均匀性"
            and standard == "gbt28043"
            and replicate_type != "single"
            and len({len(repeats) for repeats, _, _ in group.values()}) > 1
        ):
            _, row_number, original = next(iter(group.values()))
            cell = f"{get_column_letter(positions['值'] + 1)}{row_number}"
            issues.append(
                Issue("UNBALANCED_REPEATS", sheet, cell, original, "GB/T 模式需要平衡重复")
            )
        if sheet == "稳定性" and len({len(repeats) for repeats, _, _ in group.values()}) > 1:
            _, row_number, original = next(iter(group.values()))
            cell = f"{get_column_letter(positions['值'] + 1)}{row_number}"
            issues.append(
                Issue("UNBALANCED_REPEATS", sheet, cell, original, f"{name}各单元重复次数须相同")
            )
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
    populated_rows = []
    previous_df: float | None = None
    for number, row in enumerate(rows[1:], 2):
        if not any(value not in (None, "") for value in row):
            continue
        populated_rows.append(number)
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
        if sheet == "报告声称值":
            column = positions["显示小数位"]
            value = row[column] if column < len(row) else None
            cell = f"{get_column_letter(column + 1)}{number}"
            if value in (None, ""):
                issues.append(Issue("MISSING", sheet, cell, value, "复核声称值须填写显示小数位"))
            elif (
                cell not in formulas
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ):
                try:
                    if math.isfinite(value) and (value != int(value) or not 0 <= value <= 12):
                        issues.append(
                            Issue(
                                "INVALID_PRECISION",
                                sheet,
                                cell,
                                value,
                                "显示小数位须为 0 至 12 的整数",
                            )
                        )
                except OverflowError:
                    pass
        if sheet == "算法S":
            for field in SHEETS[sheet]:
                column = positions[field]
                value = row[column] if column < len(row) else None
                cell = f"{get_column_letter(column + 1)}{number}"
                if (
                    cell in formulas
                    or isinstance(value, bool)
                    or not isinstance(value, (int, float))
                ):
                    continue
                try:
                    if not math.isfinite(value):
                        continue
                except OverflowError:
                    continue
                if field == "标准差或极差" and value < 0:
                    issues.append(
                        Issue("INVALID_VALUE", sheet, cell, value, "标准差或极差不得为负")
                    )
                if field == "自由度":
                    if (
                        value != int(value)
                        or not 1 <= value <= 10
                        or (previous_df is not None and value != previous_df)
                    ):
                        issues.append(
                            Issue("INVALID_DF", sheet, cell, value, "自由度须为 1 至 10 的相同整数")
                        )
                    previous_df = float(value)
    if sheet == "算法S" and populated_rows and insufficient_units(len(populated_rows)):
        column = positions["标准差或极差"]
        number = populated_rows[0]
        row = rows[number - 1]
        issues.append(
            Issue(
                "INSUFFICIENT_SAMPLES",
                sheet,
                f"{get_column_letter(column + 1)}{number}",
                row[column] if column < len(row) else None,
                "算法 S 需要至少两个结果",
            )
        )
    return issues


def _check_batches(rows: list[list[Any]], mapping: dict[str, Any]) -> list[Issue]:
    """在导入前定位候选批次缺失、重复、无效状态及引用。"""
    if not rows:
        return []
    positions = _positions(rows[0], "候选批次", mapping)
    issues: list[Issue] = []
    seen: set[str] = set()
    references: list[tuple[str, str, Any]] = []
    for number, row in enumerate(rows[1:], 2):
        if not any(value not in (None, "") for value in row):
            continue

        def value(field: str, current_row: list[Any] = row) -> Any:
            column = positions[field]
            return current_row[column] if column < len(current_row) else None

        def add(
            category: str,
            field: str,
            message: str,
            row_number: int = number,
            current_row: list[Any] = row,
        ) -> None:
            column = positions[field]
            cell = f"{get_column_letter(column + 1)}{row_number}"
            raw = current_row[column] if column < len(current_row) else None
            issues.append(Issue(category, "候选批次", cell, raw, message))

        for field in ("批次编号", "物品", "目标量值", "材质", "来源", "制备日期", "状态"):
            if value(field) in (None, ""):
                add("MISSING", field, "必填值缺失")
        ident = value("批次编号")
        if ident not in (None, ""):
            if str(ident) in seen:
                add("DUPLICATE", "批次编号", "批次编号重复")
            seen.add(str(ident))
        status = value("状态")
        if status not in (None, "") and status not in ENUMS["候选批次.状态"]:
            add("INVALID_CONFIG", "状态", "候选批次状态无效")
        if status in ("失败", "弃用") and not str(value("处理理由") or "").strip():
            add("MISSING", "处理理由", "失败或弃用须填写理由")
        raw = value("预实验结果")
        if raw not in (None, ""):
            try:
                numbers = [float(item.strip()) for item in str(raw).split(",")]
                valid = bool(numbers) and all(math.isfinite(number) for number in numbers)
            except (ValueError, OverflowError):
                valid = False
            if not valid:
                add("NON_NUMERIC", "预实验结果", "须为逗号分隔的有限数")
        reference = value("关联批次")
        if reference not in (None, ""):
            references.append(
                (
                    str(reference),
                    f"{get_column_letter(positions['关联批次'] + 1)}{number}",
                    reference,
                )
            )
    for reference, cell, original in references:
        if reference not in seen:
            issues.append(Issue("INVALID_REFERENCE", "候选批次", cell, original, "关联批次不存在"))
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
        "delta_e",
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
        "u_trans",
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
    path: str | Path | BytesIO,
    mapping: dict[str, Any] | None = None,
    *,
    encoding: str = "utf-8-sig",
    csv_sheet: str = "均匀性",
) -> list[Issue]:
    """只读检查测量表；CSV 按显式编码严格解码，默认兼容 UTF-8 BOM。"""
    source = path if isinstance(path, BytesIO) else Path(path)
    suffix = ".xlsx" if isinstance(source, BytesIO) else source.suffix.lower()
    mapping = mapping or {}
    if suffix == ".csv" and isinstance(source, Path):
        if csv_sheet not in MEASUREMENT_SHEETS:
            raise InputError("CSV 工作表类型无效")
        try:
            with source.open("r", encoding=encoding, errors="strict", newline="") as stream:
                rows = list(csv.reader(stream))
        except (UnicodeDecodeError, LookupError) as exc:
            raise InputError("CSV 编码错误；若文件为 GBK，请显式指定 --encoding gbk") from exc
        measurand_issues = _unsupported_measurand(csv_sheet, rows)
        wide = wide_to_long(csv_sheet, rows, mapping)
        if wide:
            normalized, csv_origins = wide
            return measurand_issues + [
                _restore_origin(issue, csv_origins, rows)
                for issue in _check_rows(csv_sheet, normalized, [], {}, csv_numbers=True)
            ]
        return measurand_issues + _check_rows(csv_sheet, rows, [], mapping, csv_numbers=True)
    if suffix != ".xlsx":
        raise InputError("只支持 XLSX 或 CSV")
    if isinstance(source, BytesIO):
        payload = source.getvalue()
        book = load_workbook(BytesIO(payload), data_only=False, read_only=True)
        values = load_workbook(BytesIO(payload), data_only=True, read_only=True)
    else:
        book = load_workbook(source, data_only=False, read_only=True)
        values = load_workbook(source, data_only=True, read_only=True)
    has_measurand = any(
        _unsupported_measurand(
            sheet, [list(row) for row in book[sheet].iter_rows(values_only=True)]
        )
        for sheet in DATA_SHEETS
        if sheet in book.sheetnames
    )
    has_measurand_config = "被测量配置" in book.sheetnames and any(
        any(value not in (None, "") for value in row)
        for row in book["被测量配置"].iter_rows(min_row=2, values_only=True)
    )
    if has_measurand or has_measurand_config:
        book.close()
        values.close()
        editable = load_workbook(BytesIO(payload) if isinstance(source, BytesIO) else source)
        try:
            separated = split_measurands(editable, mapping)
        finally:
            editable.close()
        separated_issues = []
        for item in separated:
            for issue in inspect_input(BytesIO(item["bytes"]), mapping):
                original = item["sources"].get(f"{issue.sheet}!{issue.cell}")
                sheet, cell = original.split("!", 1) if original else (issue.sheet, issue.cell)
                separated_issues.append(
                    replace(
                        issue,
                        sheet=sheet,
                        cell=cell,
                        message=f"被测量 {item['name']}：{issue.message}",
                    )
                )
        return separated_issues
    try:
        issues: list[Issue] = []
        for pending in ("趋势稳定性", "传递标准复测"):
            if pending in book.sheetnames and any(
                any(value not in (None, "") for value in row)
                for row in book[pending].iter_rows(min_row=2, values_only=True)
            ):
                issues.append(
                    Issue(
                        "NOT_IMPLEMENTED",
                        pending,
                        "A1",
                        None,
                        "该表尚未接入运行流程，不能忽略后继续计算",
                    )
                )
        replicate_type = "technical"
        layout = None
        config_values: dict[str, Any] = {}
        config_cells: dict[str, str] = {}
        stability_groups: set[str] = set()
        homogeneity_present = False
        calculation_data_present = False
        if "方法配置" in book.sheetnames:
            config_rows = [list(row) for row in book["方法配置"].iter_rows(values_only=True)]
            if config_rows:
                positions = _positions(config_rows[0], "方法配置", mapping)
                for index, row in enumerate(config_rows[1:], 2):
                    key = row[positions["字段"]] if positions["字段"] < len(row) else None
                    match = re.search(r"（([a-zA-Z_][a-zA-Z_0-9]*)）$", str(key))
                    field = match.group(1) if match else str(key)
                    col = positions["值"]
                    value = row[col] if col < len(row) else None
                    if field == "stability_method" and value in STABILITY_METHOD_ALIASES:
                        value = STABILITY_METHOD_ALIASES[value]
                    if (
                        field
                        in (
                            "strict_homogeneity",
                            "reference_uncertainty_negligible",
                            "algorithm_a_simplified",
                        )
                        and isinstance(value, str)
                        and value in ("启用", "关闭", "TRUE", "FALSE")
                    ):
                        value = value in ("启用", "TRUE")
                    config_values[field] = value
                    config_cells[field] = f"{get_column_letter(col + 1)}{index}"
                    if field == "layout":
                        if value not in (None, "") and value not in ENUMS["layout"]:
                            issues.append(
                                Issue(
                                    "INVALID_CONFIG",
                                    "方法配置",
                                    f"{get_column_letter(col + 1)}{index}",
                                    value,
                                    "布局应为 long 或 wide",
                                )
                            )
                        else:
                            layout = value or None
                        continue
                    if field != "replicate_type":
                        continue
                    if value not in (None, "") and value not in ENUMS["replicate_type"]:
                        issues.append(
                            Issue(
                                "INVALID_CONFIG",
                                "方法配置",
                                f"{get_column_letter(col + 1)}{index}",
                                value,
                                "重复性质无效",
                            )
                        )
                    else:
                        replicate_type = value or "technical"
        project_unit: Any = None
        if "项目信息" not in book.sheetnames:
            issues.append(Issue("MISSING_SHEET", "项目信息", "A1", None, "缺少项目信息工作表"))
        else:
            metadata_rows = [list(row) for row in book["项目信息"].iter_rows(values_only=True)]
            if not metadata_rows:
                raise InputError("项目信息：缺少表头")
            pos = _positions(metadata_rows[0], "项目信息", mapping)
            fields: dict[str, tuple[Any, int]] = {}
            for number, row in enumerate(metadata_rows[1:], 2):
                key = row[pos["字段"]] if pos["字段"] < len(row) else None
                if key:
                    value = row[pos["值"]] if pos["值"] < len(row) else None
                    fields[str(key)] = (value, number)
            for name in ("项目名称", "单位"):
                value, number = fields.get(name, (None, 1))
                if not value:
                    cell = f"{get_column_letter(pos['值'] + 1)}{number}" if number != 1 else "A1"
                    issues.append(Issue("MISSING", "项目信息", cell, value, f"{name}必填"))
            project_unit = fields.get("单位", (None, 1))[0]
        if not set(MEASUREMENT_SHEETS).intersection(book.sheetnames):
            raise InputError("缺少可检查的测量工作表")
        for sheet in MEASUREMENT_SHEETS:
            if sheet not in book.sheetnames:
                continue
            cells = list(book[sheet].iter_rows())
            rows = [[cell.value for cell in row] for row in cells]
            original_rows = rows
            formulas = {cell.coordinate for row in cells for cell in row if cell.data_type == "f"}
            issues.extend(_unsupported_measurand(sheet, rows))
            cached = [list(row) for row in values[sheet].iter_rows(values_only=True)]
            wide = wide_to_long(sheet, rows, mapping, layout if sheet != "参加者结果" else None)
            origins: dict[str, str] = {}
            effective_mapping = mapping
            if wide:
                rows, origins = wide
                effective_mapping = {}
                cached_original = cached
                cached = [rows[0]]
                for row_number, row in enumerate(rows[1:], 2):
                    current = []
                    for column in range(1, len(row) + 1):
                        address = origins[f"{get_column_letter(column)}{row_number}"]
                        letter, source_row = coordinate_from_string(address)
                        source_col = column_index_from_string(letter) - 1
                        cached_row = (
                            cached_original[source_row - 1]
                            if source_row <= len(cached_original)
                            else []
                        )
                        current.append(
                            cached_row[source_col] if source_col < len(cached_row) else None
                        )
                    cached.append(current)
                formulas = {
                    virtual for virtual, original in origins.items() if original in formulas
                }
            found = _check_rows(
                sheet,
                rows,
                cached,
                effective_mapping,
                formulas=formulas,
                replicate_type=replicate_type,
                standard=config_values.get("criterion_standard") or "gl003",
            )
            populated = [row for row in rows[1:] if any(value not in (None, "") for value in row)]
            calculation_data_present |= bool(populated)
            if sheet == "均匀性":
                homogeneity_present = bool(populated)
            elif sheet == "稳定性" and rows:
                group_col = _positions(rows[0], sheet, effective_mapping)["时间组"]
                stability_groups.update(
                    str(row[group_col])
                    for row in populated
                    if group_col < len(row) and row[group_col] not in (None, "")
                )
            issues.extend(_restore_origin(issue, origins, original_rows) for issue in found)
            if rows:
                position = _positions(rows[0], sheet, effective_mapping)["单位"]
                for index, row in enumerate(rows[1:], 2):
                    value = row[position] if position < len(row) else None
                    if value in (None, ""):
                        continue
                    if project_unit is None:
                        project_unit = value
                    elif value != project_unit:
                        virtual = f"{get_column_letter(position + 1)}{index}"
                        cell = origins.get(virtual, virtual)
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
            if sheet in ("报告声称值", "算法S", "方法配置", "指定值与不确定度", "候选批次"):
                cells = list(book[sheet].iter_rows())
                rows = [[cell.value for cell in row] for row in cells]
                formulas = {
                    cell.coordinate for row in cells for cell in row if cell.data_type == "f"
                }
                if sheet == "候选批次":
                    issues.extend(_check_batches(rows, mapping))
                elif sheet in ("报告声称值", "算法S"):
                    if sheet == "报告声称值":
                        issues.extend(_unsupported_measurand(sheet, rows))
                    elif any(any(value not in (None, "") for value in row) for row in rows[1:]):
                        calculation_data_present = True
                    issues.extend(_check_numeric_table(sheet, rows, mapping, formulas))
                else:
                    if sheet == "指定值与不确定度":
                        calculation_data_present |= any(
                            len(row) >= 2 and row[0] == "method" and row[1] not in (None, "")
                            for row in rows[1:]
                        )
                    issues.extend(_check_numeric_config(sheet, rows, mapping, formulas))
            for row in book[sheet].iter_rows():
                for cell in row:
                    if cell.data_type != "f":
                        continue
                    cached = values[sheet][cell.coordinate].value
                    category = "FORMULA_NO_CACHE" if cached is None else "FORMULA"
                    message = "公式没有缓存值" if cached is None else "现有计算器不接受公式"
                    issues.append(Issue(category, sheet, cell.coordinate, cell.value, message))
        method = config_values.get("stability_method") or "two_sample"
        baseline_source = config_values.get("baseline_source") or (
            "homogeneity" if method == "mean_difference" else "baseline_group"
        )
        problem = stability_structure_problem(
            stability_groups,
            method,
            baseline_source,
            homogeneity_present,
            config_values.get("reference"),
            config_values.get("criterion_standard") or "gl003",
            requires_reference=(config_values.get("stability_design") or "independent")
            == "independent"
            and config_values.get("reference_uncertainty_negligible", True) is not False,
        )
        if problem:
            category, message = problem
            field = "reference" if category == "MISSING_CONFIG" else "stability_method"
            sheet = "方法配置" if category in ("MISSING_CONFIG", "INVALID_CONFIG") else "稳定性"
            cell = config_cells.get(field, "B1") if sheet == "方法配置" else "A1"
            issues.append(Issue(category, sheet, cell, None, message))
        if (
            stability_groups
            and config_values.get("criterion_standard") == "gbt28043"
            and not problem
        ):
            try:
                gbt_period_options(config_values, {group: None for group in stability_groups})
            except InputError as exc:
                field = "stability_period_options"
                if "均值标准不确定度" in str(exc):
                    for candidate in ("stability_u1", "stability_u2"):
                        value = config_values.get(candidate)
                        if value in (None, ""):
                            continue
                        try:
                            valid = (
                                not isinstance(value, bool)
                                and isinstance(value, (int, float))
                                and math.isfinite(value)
                                and value >= 0
                            )
                        except OverflowError:
                            valid = False
                        if not valid:
                            field = candidate
                            break
                issues.append(
                    Issue(
                        "INVALID_CONFIG",
                        "方法配置",
                        config_cells.get(field, "B1"),
                        config_values.get(field),
                        str(exc),
                    )
                )
        if not calculation_data_present:
            issues.append(Issue("NO_DATA", "均匀性", "A1", None, "没有可计算的数据"))
        unique: list[Issue] = []
        for issue in issues:
            if issue not in unique:
                unique.append(issue)
        return unique
    finally:
        book.close()
        values.close()
