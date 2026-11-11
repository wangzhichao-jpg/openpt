# SPDX-License-Identifier: Apache-2.0
"""固定模板及来源定位。"""

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


def read_workbook(path: str | Path) -> dict[str, Any]:
    """导入 GL003 和 GL002 输入并记录测量单元格来源。"""
    book = load_workbook(Path(path), data_only=False)
    missing = set(SHEETS) - set(book.sheetnames)
    if missing:
        raise InputError("缺少工作表：" + ", ".join(sorted(missing)))

    def rows(name: str) -> Iterator[Any]:
        ws = book[name]
        headers = [ws.cell(1, i).value for i in range(1, len(SHEETS[name]) + 1)]
        if name == "报告声称值" and headers[-1] is None:
            headers[-1] = "时间组"  # 兼容旧模板
        if headers != SHEETS[name]:
            raise InputError(f"{name}!1 表头错误")
        for cells in ws.iter_rows(min_row=2, max_col=len(SHEETS[name])):
            if not any(c.value is not None for c in cells):
                continue
            if any(c.data_type == "f" for c in cells):
                raise InputError(f"{name}!{cells[0].row}: 不接受公式")
            yield cells

    info_rows = list(rows("项目信息"))
    info = {str(r[0].value): r[1].value for r in info_rows if r[0].value}
    info_locations = {str(r[0].value): r[1].coordinate for r in info_rows if r[0].value}
    config = {}
    for r in rows("方法配置"):
        if not r[0].value:
            continue
        label = str(r[0].value)
        match = re.search(r"（([a-zA-Z_][a-zA-Z_0-9]*)）$", label)
        key = match.group(1) if match else label
        value = r[1].value
        if key == "strict_homogeneity" and value in ("启用", "关闭"):
            value = value == "启用"
        if key == "stability_method" and value in ("两均值", "单均值"):
            value = {"两均值": "two_sample", "单均值": "one_sample"}[value]
        config[key] = value
    for required in ("项目名称", "单位"):
        if not info.get(required):
            position = info_locations.get(required)
            location = f"项目信息!{position}" if position else "项目信息"
            raise InputError(f"{location}: {required}必填")

    def numeric(c: Any, name: str) -> float:
        if (
            isinstance(c.value, bool)
            or not isinstance(c.value, (int, float))
            or not isfinite(c.value)
        ):
            raise InputError(f"{name}!{c.coordinate}: 数值无效")
        return float(c.value)

    measured_precision: list[int] = []

    def observations(
        name: str, stability: bool = False
    ) -> tuple[dict[str, Any], list[str], dict[str, list[str]]]:
        grouped: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
        sources = []
        for r in rows(name):
            group, uid, rep, val, unit = (
                (r[0].value, r[1].value, r[2].value, r[3], r[4].value)
                if stability
                else ("均匀性", r[0].value, r[1].value, r[2], r[3].value)
            )
            if not group or uid is None or rep is None:
                raise InputError(f"{name}!{r[0].row}: 缺少分组或编号")
            if unit != info["单位"]:
                raise InputError(f"{name}!{r[-1].coordinate}: 单位不一致")
            key = (str(group), str(uid))
            rep = str(rep)
            if rep in grouped[key]:
                raise InputError(f"{name}!{r[0].row}: 重复编号")
            grouped[key][rep] = numeric(val, name)
            number_format = re.search(r"\.([0#]+)", val.number_format)
            if number_format:
                measured_precision.append(len(number_format.group(1)))
            else:
                exponent = Decimal(str(val.value)).as_tuple().exponent
                measured_precision.append(max(0, -exponent) if isinstance(exponent, int) else 0)
            sources.append(f"{name}!{val.coordinate}")
        groups = defaultdict(list)
        unit_ids: dict[str, list[str]] = defaultdict(list)
        for (group, uid), values in grouped.items():
            groups[group].append(list(values.values()))
            unit_ids[group].append(uid)
        for group, items in groups.items():
            if len({len(x) for x in items}) > 1:
                raise InputError(f"{name}: {group} 重复数不平衡")
            if not stability and items and len(items[0]) < 2:
                raise InputError(f"{sources[0]}: 每个单元至少需要两次重复")
        return dict(groups), sources, dict(unit_ids)

    hom, hs, hom_ids = observations("均匀性")
    stab, ss, stab_ids = observations("稳定性", True)
    participants = []
    for r in rows("参加者结果"):
        if r[0].value is None or r[2].value != info["单位"]:
            raise InputError(f"参加者结果!{r[0].row}: 编号或单位错误")
        participants.append(
            {
                "id": str(r[0].value),
                "value": numeric(r[1], "参加者结果"),
                "source": f"参加者结果!{r[1].coordinate}",
            }
        )
    claims = []
    for r in rows("报告声称值"):
        if r[0].value is None or r[1].value is None or not r[3].value:
            raise InputError(f"报告声称值!{r[0].row}: 项目、声称值及来源必填")
        claims.append(
            {
                "name": str(r[0].value),
                "value": numeric(r[1], "报告声称值"),
                "digits": r[2].value,
                "source": str(r[3].value),
                "model": r[4].value,
                "timegroup": r[5].value,
                "cell": f"报告声称值!{r[1].coordinate}",
            }
        )
    return {
        "info": info,
        "config": config,
        "homogeneity": hom.get("均匀性", []),
        "homogeneity_units": hom_ids.get("均匀性", []),
        "stability": stab,
        "stability_units": stab_ids,
        "participants": participants,
        "claims": claims,
        "sources": hs + ss,
        "data_decimal_places": max(measured_precision) if measured_precision else None,
    }
