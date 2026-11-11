# SPDX-License-Identifier: Apache-2.0
"""固定模板、输入校验及来源定位。"""

import re
from collections import defaultdict
from collections.abc import Iterator
from decimal import Decimal
from math import isfinite
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation

from ..errors import InputError

SHEETS = {
    "项目信息": ["字段", "值"],
    "方法配置": ["字段", "值"],
    "均匀性": ["单元编号", "重复编号", "值", "单位"],
    "稳定性": ["时间组", "单元编号", "重复编号", "值", "单位"],
    "参加者结果": ["参加者编号", "值", "单位"],
    "报告声称值": ["统计量", "声称值", "显示小数位", "来源", "报告模型", "时间组"],
}


def template(path: str | Path) -> None:
    """生成用于 GL003 和 GL002 计算的空白输入模板。"""
    book = Workbook()
    book.remove(book.active)
    instructions = book.create_sheet("填写说明")
    instructions.append(["填写说明", "请填写项目名称、单位及所需数据。"])
    instructions.append(["均匀性", "每个包装单元的每次技术重复填写一行；使用统一单位。"])
    instructions.append(["稳定性", "时间组填写基线、稳定期；复核声称值可指定其他时间组。"])
    instructions.append(["报告声称值", "填写统计量、数值、显示位数、来源和可选报告模型。"])
    instructions.column_dimensions["A"].width = 22
    instructions.column_dimensions["B"].width = 80
    for name, headers in SHEETS.items():
        ws = book.create_sheet(name)
        ws.append(headers)
        ws.cell(1, 1).comment = Comment("请按填写说明输入数据；不要输入 Excel 公式。", "OpenPT")
        ws.freeze_panes = "A2"
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = 22
    for row in [("项目名称", ""), ("单位", "")]:
        book["项目信息"].append(row)
    for config_row in [
        ("显著性水平（alpha）", 0.05),
        ("均匀性目标标准差（sigma）", ""),
        ("严格均匀性配置（strict_homogeneity）", False),
        ("稳定性方法（stability_method）", "two_sample"),
        ("单均值参考值（reference）", ""),
        ("指定值（assigned）", ""),
        ("能力评定标准差（sigma_pt）", ""),
        ("算法A停止规则（algorithm_a_rule）", "gl002"),
        ("z 值显示小数位（display_z_decimals）", 2),
    ]:
        book["方法配置"].append(config_row)
    for cell, options in [
        ("B4", '"启用,关闭"'),
        ("B5", '"两均值,单均值"'),
        ("B9", '"gl002,absolute,simplified"'),
    ]:
        validation = DataValidation(type="list", formula1=options)
        book["方法配置"].add_data_validation(validation)
        validation.add(book["方法配置"][cell])
    book.save(path)


def _rows(book: Any, name: str) -> Iterator[Any]:
    """检查表头和公式，再逐行返回原始单元格。"""
    ws = book[name]
    headers = [ws.cell(1, i).value for i in range(1, len(SHEETS[name]) + 1)]
    if name == "报告声称值" and headers[-1] is None:
        headers[-1] = "时间组"
    if headers != SHEETS[name]:
        raise InputError(f"{name}!1 表头错误")
    for cells in ws.iter_rows(min_row=2, max_col=len(SHEETS[name])):
        if not any(c.value is not None for c in cells):
            continue
        if any(c.data_type == "f" for c in cells):
            raise InputError(f"{name}!{cells[0].row}: 不接受公式")
        yield cells


def _numeric(cell: Any, name: str) -> float:
    """读取有限数值，不将文字隐式转换为数值。"""
    if (
        isinstance(cell.value, bool)
        or not isinstance(cell.value, (int, float))
        or not isfinite(cell.value)
    ):
        raise InputError(f"{name}!{cell.coordinate}: 数值无效")
    return float(cell.value)


def _metadata(book: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """读取项目字段和方法配置。"""
    rows = list(_rows(book, "项目信息"))
    info = {str(r[0].value): r[1].value for r in rows if r[0].value}
    locations = {str(r[0].value): r[1].coordinate for r in rows if r[0].value}
    for required in ("项目名称", "单位"):
        if not info.get(required):
            position = locations.get(required)
            location = f"项目信息!{position}" if position else "项目信息"
            raise InputError(f"{location}: {required}必填")
    config = {}
    for row in _rows(book, "方法配置"):
        if not row[0].value:
            continue
        label = str(row[0].value)
        match = re.search(r"（([a-zA-Z_][a-zA-Z_0-9]*)）$", label)
        key = match.group(1) if match else label
        value = row[1].value
        if key == "strict_homogeneity" and value in ("启用", "关闭"):
            value = value == "启用"
        if key == "stability_method" and value in ("两均值", "单均值"):
            value = {"两均值": "two_sample", "单均值": "one_sample"}[value]
        config[key] = value
    return info, config


def _precision(cell: Any) -> int:
    """优先从 Excel 数字格式提取显示小数位。"""
    number_format = re.search(r"\.([0#]+)", cell.number_format)
    if number_format:
        return len(number_format.group(1))
    exponent = Decimal(str(cell.value)).as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def _observations(
    book: Any, name: str, unit: str, precision: list[int], stability: bool = False
) -> tuple[dict[str, Any], list[str], dict[str, list[str]]]:
    """读取包装单元和重复测量，记录单元格位置。"""
    grouped: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    unit_sources: dict[tuple[str, str], str] = {}
    sources = []
    for row in _rows(book, name):
        group, uid, rep, val, actual_unit = (
            (row[0].value, row[1].value, row[2].value, row[3], row[4].value)
            if stability
            else ("均匀性", row[0].value, row[1].value, row[2], row[3].value)
        )
        if not group or uid is None or rep is None:
            raise InputError(f"{name}!{row[0].row}: 缺少分组或编号")
        if actual_unit != unit:
            raise InputError(f"{name}!{row[-1].coordinate}: 单位不一致")
        key, repeat = (str(group), str(uid)), str(rep)
        if repeat in grouped[key]:
            raise InputError(f"{name}!{row[0].row}: 重复编号")
        grouped[key][repeat] = _numeric(val, name)
        unit_sources[key] = f"{name}!{val.coordinate}"
        precision.append(_precision(val))
        sources.append(f"{name}!{val.coordinate}")
    groups: dict[str, list[list[float]]] = defaultdict(list)
    unit_ids: dict[str, list[str]] = defaultdict(list)
    for (group, uid), values in grouped.items():
        if not stability and len(values) < 2:
            raise InputError(f"{unit_sources[(group, uid)]}: 单元 {uid} 至少需要两次重复")
        groups[group].append(list(values.values()))
        unit_ids[group].append(uid)
    return dict(groups), sources, dict(unit_ids)


def _participants(book: Any, unit: str) -> list[dict[str, Any]]:
    """读取参加者结果和单元格位置。"""
    values = []
    seen: set[str] = set()
    for row in _rows(book, "参加者结果"):
        if row[0].value is None or row[2].value != unit:
            raise InputError(f"参加者结果!{row[0].row}: 编号或单位错误")
        participant_id = str(row[0].value)
        if participant_id in seen:
            raise InputError(f"参加者结果!{row[0].coordinate}: 编号重复")
        seen.add(participant_id)
        values.append(
            {
                "id": str(row[0].value),
                "value": _numeric(row[1], "参加者结果"),
                "source": f"参加者结果!{row[1].coordinate}",
            }
        )
    return values


def _claims(book: Any) -> list[dict[str, Any]]:
    """读取报告声称值及其来源。"""
    values = []
    for row in _rows(book, "报告声称值"):
        if row[0].value is None or row[1].value is None or not row[3].value:
            raise InputError(f"报告声称值!{row[0].row}: 项目、声称值及来源必填")
        values.append(
            {
                "name": str(row[0].value),
                "value": _numeric(row[1], "报告声称值"),
                "digits": row[2].value,
                "source": str(row[3].value),
                "model": row[4].value,
                "timegroup": row[5].value,
                "cell": f"报告声称值!{row[1].coordinate}",
            }
        )
    return values


def read_workbook(path: str | Path) -> dict[str, Any]:
    """导入 GL003 和 GL002 输入并记录测量单元格来源。"""
    book = load_workbook(Path(path), data_only=False)
    missing = set(SHEETS) - set(book.sheetnames)
    if missing:
        raise InputError("缺少工作表：" + ", ".join(sorted(missing)))
    info, config = _metadata(book)
    precision: list[int] = []
    hom, hs, hom_ids = _observations(book, "均匀性", info["单位"], precision)
    stab, ss, stab_ids = _observations(book, "稳定性", info["单位"], precision, True)
    return {
        "info": info,
        "config": config,
        "homogeneity": hom.get("均匀性", []),
        "homogeneity_units": hom_ids.get("均匀性", []),
        "stability": stab,
        "stability_units": stab_ids,
        "participants": _participants(book, info["单位"]),
        "claims": _claims(book),
        "sources": hs + ss,
        "data_decimal_places": max(precision) if precision else None,
    }
