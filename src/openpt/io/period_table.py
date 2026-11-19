# SPDX-License-Identifier: Apache-2.0
"""稳定性逐时间组表：合并配置并复用统一规则。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from ..config.rules import check_method_config
from .shape import period_enum_problem

SHEET = "稳定性时间组配置"
FIELDS = {
    "类型（kind）": "kind",
    "判据规则（rule）": "rule",
    "判据依据（basis）": "basis",
    "最大允许偏差（delta_e）": "delta_e",
    "后续均值标准不确定度（u2）": "u2",
    "GL003稳定性方法（stability_method）": "stability_method",
    "基线来源（baseline_source）": "baseline_source",
}
HEADERS = ["时间组", *FIELDS, "（选填）"]


@dataclass(frozen=True)
class PeriodTableIssue:
    """表内可定位问题。"""

    cell: str
    value: Any
    message: str
    code: str = "PERIOD_CRITERIA"
    field: str = "stability_period_options"


def create_period_sheet(book: Any) -> None:
    """在模板中提供空表和枚举下拉。"""
    if SHEET in book.sheetnames:
        return
    ws = book.create_sheet(SHEET)
    if "填写说明" in book.sheetnames:
        instructions = book["填写说明"]
        if not any(row[0].value == SHEET for row in instructions.iter_rows(min_row=2)):
            instructions.append(
                [SHEET, "每组一行，分别设置稳定期和运输期；留空沿用全局，不得与 JSON 重复字段。"]
            )
    ws.append(HEADERS)
    ws.freeze_panes = "B2"
    for index, choices in (
        (2, "storage,transport"),
        (3, "basic,extended"),
        (4, "sigma_pt,delta_e"),
        (7, "one_sample,two_sample,mean_difference"),
        (8, "homogeneity,baseline_group"),
    ):
        validation = DataValidation(type="list", formula1=f'"{choices}"', allow_blank=True)
        ws.add_data_validation(validation)
        validation.add(f"{get_column_letter(index)}2:{get_column_letter(index)}1048576")
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 28


def merge_period_table(
    book: Any, config: dict[str, Any], groups: Any
) -> tuple[dict[str, Any], list[PeriodTableIssue]]:
    """合并表与 JSON；冲突及规则问题对应表中实际单元格。"""
    if SHEET not in book.sheetnames:
        return config, []
    ws = book[SHEET]
    rows = list(ws.iter_rows())
    if not rows:
        return config, [PeriodTableIssue("A1", None, "缺少表头")]
    headers = [cell.value for cell in rows[0]]
    required = HEADERS[:-1]
    if any(headers.count(header) != 1 for header in required):
        return config, [PeriodTableIssue("A1", None, "表头缺失或重复：须包含时间组及全部配置字段")]
    positions = {header: headers.index(header) for header in required}
    raw = config.get("stability_period_options")
    if period_enum_problem(raw):
        return config, []  # 方法配置的 JSON 原错误由既有规则报告。
    entries = json.loads(raw) if isinstance(raw, str) else raw or {}
    merged = {key: dict(value) for key, value in entries.items()}
    issues: list[PeriodTableIssue] = []
    seen: set[str] = set()
    present = False
    for row in rows[1:]:
        cells = {header: row[index] for header, index in positions.items()}
        if all(cell.value in (None, "") for cell in cells.values()):
            continue
        present = True
        group_cell = cells["时间组"]
        raw_name = group_cell.value
        if (
            isinstance(raw_name, bool)
            or not isinstance(raw_name, (str, int, float))
            or not str(raw_name).strip()
        ):
            issues.append(
                PeriodTableIssue(group_cell.coordinate, raw_name, "时间组须为非空文字或数字")
            )
            continue
        name = str(raw_name)
        if name in seen:
            issues.append(PeriodTableIssue(group_cell.coordinate, raw_name, "时间组在表中重复"))
            continue
        seen.add(name)
        if name not in groups or name == "基线":
            issues.append(
                PeriodTableIssue(group_cell.coordinate, raw_name, "时间组不存在于稳定性数据")
            )
            continue
        entry = merged.setdefault(name, {})
        table_fields: dict[str, Any] = {}
        for header, field in FIELDS.items():
            cell = cells[header]
            if cell.value in (None, ""):
                continue
            if cell.data_type == "f":
                issues.append(PeriodTableIssue(cell.coordinate, cell.value, "配置不接受公式"))
                continue
            table_fields[field] = cell
            if field in entry:
                issues.append(
                    PeriodTableIssue(
                        cell.coordinate,
                        cell.value,
                        f"时间组 {name} 的 {field} 与方法配置 JSON 重复",
                    )
                )
            else:
                entry[field] = cell.value
        # 使用同一规则层，校验该组与合并后的其他来源；避免错误落到方法配置。
        isolated = {**config, "stability_period_options": {name: entry}}
        json_only = {**config, "stability_period_options": {name: entries.get(name, {})}}
        json_problems = {
            (issue.code, issue.message)
            for issue in check_method_config(json_only)
            if issue.field == "stability_period_options"
        }
        for issue in check_method_config(isolated):
            if (
                issue.field != "stability_period_options"
                or (issue.code, issue.message) in json_problems
            ):
                continue
            issue_field = next((f for f in table_fields if f in issue.message), None)
            if "须明确登记 baseline_source" in issue.message:
                issue_field = (
                    "stability_method" if "stability_method" in table_fields else "baseline_source"
                )
            if issue_field is None and "kind" in issue.message:
                issue_field = "kind"
            if issue_field is not None and issue_field in table_fields:
                cell = table_fields[issue_field]
                issues.append(
                    PeriodTableIssue(cell.coordinate, cell.value, issue.message, issue.code)
                )
            elif table_fields:
                cell = next(iter(table_fields.values()))
                issues.append(
                    PeriodTableIssue(cell.coordinate, cell.value, issue.message, issue.code)
                )
    if not present or issues:
        return config, issues
    return {**config, "stability_period_options": merged}, []
