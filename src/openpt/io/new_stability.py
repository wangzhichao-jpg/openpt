# SPDX-License-Identifier: Apache-2.0
"""趋势和传递标准工作表解析；输入数值及来源保持关联。"""

import json
import math
import re
from datetime import date, datetime
from typing import Any

from ..errors import InputError


def _headers(ws: Any) -> list[Any]:
    headers = [cell.value for cell in ws[1]]
    present = [header for header in headers if header not in (None, "", "（选填）")]
    if len(present) != len(set(str(header) for header in present)):
        raise InputError(f"{ws.title}!1: 表头重复")
    return headers


def _required(headers: list[Any], names: tuple[str, ...], sheet: str) -> dict[str, int]:
    if any(headers.count(name) != 1 for name in names):
        raise InputError(f"{sheet}!1: 表头缺失或重复")
    return {name: headers.index(name) + 1 for name in names}


def _value(cell: Any, *, numeric: bool = False) -> Any:
    if cell.data_type == "f":
        raise InputError(f"{cell.parent.title}!{cell.coordinate}: 不接受公式")
    value = cell.value
    if value is None or value == "":
        raise InputError(f"{cell.parent.title}!{cell.coordinate}: 必填值缺失")
    if numeric and (
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
    ):
        raise InputError(f"{cell.parent.title}!{cell.coordinate}: 须为有限数")
    return float(value) if numeric else value


def read_trend_sheet(book: Any) -> list[dict[str, Any]]:
    """长表或宽表，宽表时间列命名为“时间=数值”；空单元格视为缺失。"""
    if "趋势稳定性" not in book.sheetnames:
        return []
    ws = book["趋势稳定性"]
    headers = _headers(ws)
    long = "时间 X" in headers or "值 Y" in headers
    names = ("序列名", "时间 X", "时间单位", "值 Y") if long else ("序列名", "时间单位")
    positions = _required(headers, names, ws.title)
    time_columns: list[tuple[int, float]] = []
    if not long:
        for index, header in enumerate(headers, 1):
            if isinstance(header, str):
                match = re.fullmatch(r"时间\s*=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))", header.strip())
                if match:
                    time_columns.append((index, float(match.group(1))))
        if not time_columns:
            # 空模板可在尚未填写数据时通过。
            if ws.max_row <= 1:
                return []
            raise InputError("趋势稳定性!1: 宽表须包含时间=数值列")
        if len({x for _, x in time_columns}) != len(time_columns):
            raise InputError("趋势稳定性!1: 时间列重复")
    output = []
    for row in ws.iter_rows(min_row=2):
        if not any(cell.value not in (None, "") for cell in row):
            continue

        def get(name: str, row_number: int = row[0].row) -> Any:
            return ws.cell(row_number, positions[name])

        series, unit = _value(get("序列名")), _value(get("时间单位"))
        if not isinstance(series, str) or not series.strip() or unit not in ("天", "月", "次"):
            raise InputError(f"趋势稳定性!{row[0].row}: 序列名或时间单位无效")
        condition = None
        if "条件" in headers:
            condition_cell = ws.cell(row[0].row, headers.index("条件") + 1)
            if condition_cell.data_type == "f":
                raise InputError(f"趋势稳定性!{condition_cell.coordinate}: 不接受公式")
            condition = condition_cell.value
            if condition not in (None, "") and not isinstance(condition, str):
                raise InputError(f"趋势稳定性!{condition_cell.coordinate}: 条件须为文字")
        if long:
            xcell, ycell = get("时间 X"), get("值 Y")
            output.append(
                {
                    "series": series,
                    "time_unit": unit,
                    "x": _value(xcell, numeric=True),
                    "y": _value(ycell, numeric=True),
                    "source": f"趋势稳定性!{ycell.coordinate}",
                    "time_source": f"趋势稳定性!{xcell.coordinate}",
                    "condition": condition,
                }
            )
        else:
            for col, x in time_columns:
                ycell = ws.cell(row[0].row, col)
                output.append(
                    {
                        "series": series,
                        "time_unit": unit,
                        "x": x,
                        "y": _value(ycell, numeric=True),
                        "source": f"趋势稳定性!{ycell.coordinate}",
                        "time_source": f"趋势稳定性!{ws.cell(1, col).coordinate}",
                        "condition": condition,
                    }
                )
    return output


def _json_object(value: Any, label: str, expected: type) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                raise InputError(f"{label}: JSON 键重复")
            result[key] = item
        return result

    try:
        result = json.loads(value, object_pairs_hook=pairs) if isinstance(value, str) else value
    except (TypeError, ValueError):
        raise InputError(f"{label}: JSON 格式无效") from None
    if not isinstance(result, expected):
        raise InputError(f"{label}: JSON 类型无效")
    return result


def read_transfer_config(book: Any) -> dict[str, dict[str, Any]]:
    """逐标准器及校准点登记窗口、判据、来源与可选不确定度机制。"""
    if "传递标准配置" not in book.sheetnames:
        return {}
    ws = book["传递标准配置"]
    names = (
        "传递标准编号",
        "校准点",
        "单位",
        "计算区间",
        "判据JSON",
        "不确定度JSON",
        "出处",
        "汇总变差",
    )
    positions = _required(_headers(ws), names, ws.title)
    result = {}
    for row in ws.iter_rows(min_row=2):
        if not any(cell.value not in (None, "") for cell in row):
            continue
        cells = {name: ws.cell(row[0].row, positions[name]) for name in names}
        standard, point, unit, window = (str(_value(cells[name])) for name in names[:4])
        if "|" in standard or "|" in point:
            raise InputError("传递标准编号和校准点不能包含竖线")
        key = f"{standard}|{point}"
        if key in result:
            raise InputError(f"传递标准配置!{cells['校准点'].coordinate}: 配置重复")
        if window not in ("all", "transfer_only"):
            raise InputError(f"传递标准配置!{cells['计算区间'].coordinate}: 计算区间无效")
        criteria = _json_object(_value(cells["判据JSON"]), "判据JSON", list)
        if not criteria or not all(isinstance(rule, dict) for rule in criteria):
            raise InputError("判据JSON 须为非空对象列表")
        raw = cells["不确定度JSON"].value
        uncertainty = (
            _json_object(_value(cells["不确定度JSON"]), "不确定度JSON", dict)
            if raw not in (None, "")
            else {}
        )
        source = str(_value(cells["出处"]))
        summary = cells["汇总变差"]
        result[key] = {
            "standard": standard,
            "point": point,
            "unit": unit,
            "window": window,
            "criteria": criteria,
            "uncertainty": uncertainty,
            "source": source,
            "summarized_delta": _value(summary, numeric=True)
            if summary.value not in (None, "")
            else None,
        }
    return result


def read_transfer_sheet(book: Any) -> list[dict[str, Any]]:
    """读取每次测量的标准器、校准点、阶段和原单元格。"""
    if "传递标准复测" not in book.sheetnames:
        return []
    ws = book["传递标准复测"]
    names = ("传递标准编号", "校准点", "测量序号", "日期", "阶段", "测量值", "单位")
    positions = _required(_headers(ws), names, ws.title)
    output = []
    seen: set[tuple[str, str, str]] = set()
    for row in ws.iter_rows(min_row=2):
        if not any(cell.value not in (None, "") for cell in row):
            continue
        cells = {name: ws.cell(row[0].row, positions[name]) for name in names}
        standard, point, order, day, stage, unit = (
            _value(cells[name]) for name in names if name != "测量值"
        )
        if stage not in ("传递前", "传递中", "传递后"):
            raise InputError(f"传递标准复测!{cells['阶段'].coordinate}: 阶段无效")
        if not isinstance(day, (str, date, datetime)):
            raise InputError(f"传递标准复测!{cells['日期'].coordinate}: 日期无效")
        key = (str(standard), str(point), str(order))
        if key in seen:
            raise InputError(f"传递标准复测!{cells['测量序号'].coordinate}: 测量序号重复")
        seen.add(key)
        output.append(
            {
                "standard": str(standard),
                "point": str(point),
                "order": str(order),
                "date": day.isoformat() if isinstance(day, (date, datetime)) else day,
                "stage": stage,
                "value": _value(cells["测量值"], numeric=True),
                "unit": str(unit),
                "source": f"传递标准复测!{cells['测量值'].coordinate}",
            }
        )
    return output
