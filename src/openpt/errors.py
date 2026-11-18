# SPDX-License-Identifier: Apache-2.0
"""输入错误及可定位的提示。"""

import json
import re


class InputError(ValueError):
    """输入无法用于选定计算；可包含工作表和单元格位置。"""


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
