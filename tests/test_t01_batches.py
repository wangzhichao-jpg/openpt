# SPDX-License-Identifier: Apache-2.0
"""候选批次登记、关联和比较。"""

from pathlib import Path

import pytest
from openpyxl import load_workbook

from openpt.errors import InputError
from openpt.io.excel import read_workbook, template


def test_batch_trace_and_comparison(tmp_path: Path) -> None:
    """登记候选及失败批次，保留人工选用状态和预实验统计量。"""
    path = tmp_path / "input.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "虚构项目"
    book["项目信息"]["B3"] = "mg"
    sheet = book["候选批次"]
    sheet.append(["A", "物品", 1, "材质", "来源", "2025-01-01", "1,2,3", "失败", "不足", ""])
    sheet.append(["B", "物品", 1, "材质", "来源", "2025-01-02", "2,3,4", "候选", "", "A"])
    book.save(path)
    batches = read_workbook(path)["batches"]
    assert [b["状态"] for b in batches] == ["失败", "候选"]
    assert batches[0]["预实验均值"] == 2 and batches[0]["预实验标准差"] == 1
    assert batches[1]["关联批次"] == "A"
    sheet["I2"] = None
    book.save(path)
    with pytest.raises(InputError, match="须填写理由"):
        read_workbook(path)
    sheet["I2"] = "不足"
    sheet["J3"] = "不存在"
    book.save(path)
    with pytest.raises(InputError, match="关联批次"):
        read_workbook(path)
