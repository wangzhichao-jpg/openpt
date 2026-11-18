# SPDX-License-Identifier: Apache-2.0
"""输入错误及可定位的提示。"""

import json
import re
from collections.abc import Callable
from typing import Any

_MISSING = object()


class InputError(ValueError):
    """输入错误；字段定位信息不改变原始错误字符串。"""

    def __init__(
        self,
        message: str,
        *,
        sheet: str | None = None,
        field: str | None = None,
        fields: list[str] | None = None,
        issues: list[dict[str, Any]] | None = None,
        allowed: str | None = None,
        hint: str | None = None,
        value: Any = _MISSING,
    ) -> None:
        super().__init__(message)
        self.sheet = sheet
        self.field = field
        self.fields = fields or []
        self.issues = issues or []
        self.allowed = allowed
        self.hint = hint
        self.value = value


def locate(exc: InputError, data: dict[str, Any]) -> InputError:
    """用输入工作簿的字段位置补全错误；无字段时不改变原消息。"""
    if not exc.field and not exc.fields:
        return InputError(f"『{exc.sheet}』：{exc}") if exc.sheet else exc
    sheet = exc.sheet or "指定值与不确定度"
    if exc.fields:
        pieces = []
        for field in exc.fields:
            entry = data.get("_cells", {}).get((sheet, field))
            if entry:
                cell, value = entry
                match = re.search(r"\d+", cell)
                row = f"第{match.group()}行" if match else ""
                shown = (
                    "空白"
                    if value is None or value == ""
                    else f"「{value}」"
                    if isinstance(value, str)
                    else str(value)
                )
                pieces.append(f"{row} {field}（{cell}，当前值：{shown}）")
            else:
                pieces.append(f"字段 {field}")
        message = f"『{sheet}』" + "、".join(pieces) + f"：{exc}"
        if exc.allowed:
            message += f"；允许值/要求：{exc.allowed}"
        if exc.hint:
            message += f"；修改建议：{exc.hint}"
        return InputError(message, issues=exc.issues)
    cell_info = data.get("_cells", {}).get((sheet, exc.field))
    value = exc.value
    location = f"『{sheet}』字段 {exc.field}"
    if cell_info:
        cell, value = cell_info
        match = re.search(r"\d+", cell)
        row = f"第{match.group()}行" if match else ""
        shown = (
            "空白"
            if value is None or value == ""
            else f"「{value}」"
            if isinstance(value, str)
            else str(value)
        )
        location = f"『{sheet}』{row}（{cell}，当前值：{shown}）：{exc.field}"
    message = f"{location}：{exc}"
    if exc.allowed:
        message += f"；允许值/要求：{exc.allowed}"
    if exc.hint:
        message += f"；修改建议：{exc.hint}"
    return InputError(message, issues=exc.issues)


def sheet_call(sheet: str, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """为测量表计算中缺少定位的输入错误补充工作表。"""
    try:
        return function(*args, **kwargs)
    except InputError as exc:
        if not exc.sheet and not exc.field and not exc.fields:
            exc.sheet = sheet
        raise


def format_error(exc: Exception) -> str:
    """将结构化输入问题转换为完整、带位置的编号清单。"""
    message = str(exc)
    prefix = "输入校验问题："
    if not message.startswith(prefix):
        return message or "请检查工作簿中的数据和字段。"
    try:
        issues = json.loads(message[len(prefix) :])
        lines = []
        for index, issue in enumerate(issues, 1):
            cell = issue.get("cell", "")
            match = re.search(r"\d+", cell)
            row = f"第{match.group()}行" if match else ""
            value = issue.get("original")
            shown = (
                "空白"
                if value is None or value == ""
                else f"「{value}」"
                if isinstance(value, str)
                else str(value)
            )
            location = f"{cell}，" if cell else ""
            lines.append(
                f"{index}. 『{issue.get('sheet', '')}』{row}"
                f"（{location}当前值：{shown}）：{issue.get('message', '')}"
            )
        return "输入校验问题：\n" + "\n".join(lines)
    except (ValueError, TypeError, AttributeError):
        return message
