# SPDX-License-Identifier: Apache-2.0
"""宽表到长表的只读映射；每个虚拟单元格都保留原始地址。"""

import re
from typing import Any

from openpyxl.utils import get_column_letter

from ..config.catalog import ENUMS
from ..errors import InputError


def wide_to_long(
    sheet: str,
    rows: list[list[Any]],
    mapping: dict[str, Any],
    layout: str | None = None,
) -> tuple[list[list[Any]], dict[str, str]] | None:
    """识别并展开宽表，返回长表值及虚拟地址到原单元格地址的映射。"""
    if layout not in (None, "") and layout not in ENUMS["layout"]:
        raise InputError("layout 应为 long 或 wide")
    if sheet not in ("均匀性", "稳定性") or not rows:
        return None
    headers = rows[0]
    measurements = [
        (index, match.group(1))
        for index, header in enumerate(headers)
        if isinstance(header, str) and (match := re.fullmatch(r"测定\s*([1-9][0-9]*)", header))
    ]
    has_data = any(any(value not in (None, "") for value in row) for row in rows[1:])
    aliases = mapping.get(sheet, {})
    if not isinstance(aliases, dict):
        raise InputError(f"{sheet} 的列映射必须是对象")
    long_value = aliases.get("值", "值") in headers
    if measurements and long_value:
        raise InputError(f"{sheet}：同时包含长表值列和宽表测定列，格式不明确")
    if not measurements:
        if layout == "wide" and has_data:
            raise InputError(f"{sheet}：宽表缺少测定1、测定2等列")
        return None
    if layout == "long" and has_data:
        raise InputError(f"{sheet}：配置为长表但发现宽表测定列")
    if len({number for _, number in measurements}) != len(measurements):
        raise InputError(f"{sheet}：宽表测定编号重复")
    if set(aliases) - {"单元编号", "单位", "时间组"}:
        raise InputError(f"{sheet}：宽表列映射仅支持单元编号、时间组和单位")
    fields = (["时间组"] if sheet == "稳定性" else []) + ["单元编号", "单位"]
    positions = {}
    for field in fields:
        label = aliases.get(field, field)
        if not isinstance(label, str) or headers.count(label) != 1:
            raise InputError(f"{sheet}：列 {label!r} 不存在或不唯一")
        positions[field] = headers.index(label)
    if len(set(positions.values())) != len(positions):
        raise InputError(f"{sheet}：多个字段映射到同一列")
    output: list[list[Any]] = [
        (["时间组"] if sheet == "稳定性" else []) + ["单元编号", "重复编号", "值", "单位"]
    ]
    origins: dict[str, str] = {}
    for row_number, row in enumerate(rows[1:], 2):
        if not any(value not in (None, "") for value in row):
            continue
        for index, repeat in measurements:
            cols = ([positions["时间组"]] if sheet == "稳定性" else []) + [
                positions["单元编号"],
                positions["单元编号"],
                index,
                positions["单位"],
            ]
            virtual = [row[col] if col < len(row) else None for col in cols]
            virtual[-3] = repeat
            output.append(virtual)
            for column, source in enumerate(cols, 1):
                origins[f"{get_column_letter(column)}{len(output)}"] = (
                    f"{get_column_letter(source + 1)}{row_number}"
                )
    return output, origins
