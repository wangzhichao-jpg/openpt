# SPDX-License-Identifier: Apache-2.0
"""新稳定性工作表的合成输入测试。"""

import pytest
from openpyxl import Workbook

from openpt.errors import InputError
from openpt.io.excel import read_workbook, template
from openpt.io.new_stability import read_transfer_sheet, read_trend_sheet
from openpt.io.validation import inspect_input


def test_trend_long_and_wide_provenance() -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "趋势稳定性"
    sheet.append(["序列名", "时间 X", "时间单位", "值 Y"])
    sheet.append(["样品A", 0, "天", 1.25])
    records = read_trend_sheet(book)
    assert records[0]["source"] == "趋势稳定性!D2"
    sheet.delete_rows(1, sheet.max_row)
    sheet.append(["序列名", "时间单位", "时间=0", "时间=2"])
    sheet.append(["样品A", "天", 1.25, 1.3])
    records = read_trend_sheet(book)
    assert [(r["x"], r["y"], r["source"]) for r in records] == [
        (0.0, 1.25, "趋势稳定性!C2"),
        (2.0, 1.3, "趋势稳定性!D2"),
    ]
    sheet["D2"] = None
    with pytest.raises(InputError, match="D2"):
        read_trend_sheet(book)
    sheet["D2"] = "=1+1"
    with pytest.raises(InputError, match="D2"):
        read_trend_sheet(book)


@pytest.mark.parametrize("sheet_name", ["传递标准复测"])
def test_not_yet_connected_fails_closed(tmp_path, sheet_name: str) -> None:
    from openpyxl import load_workbook

    path = tmp_path / "input.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "合成"
    book["项目信息"]["B3"] = "V"
    sheet = book.create_sheet(sheet_name)
    sheet.append(["字段"])
    sheet.append(["非空数据"])
    book.save(path)
    assert any(
        issue.category == "NOT_IMPLEMENTED" and issue.sheet == sheet_name
        for issue in inspect_input(path)
    )
    with pytest.raises(InputError, match="尚未接入运行流程"):
        read_workbook(path)


def test_transfer_stage_and_duplicates() -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "传递标准复测"
    sheet.append(["传递标准编号", "校准点", "测量序号", "日期", "阶段", "测量值", "单位"])
    sheet.append(["STD1", "P1", 1, "2025-01-01", "传递中", 2.0, "V"])
    record = read_transfer_sheet(book)[0]
    assert record["source"] == "传递标准复测!F2" and record["stage"] == "传递中"
    sheet.append(["STD1", "P1", 1, "2025-01-02", "传递后", 2.1, "V"])
    with pytest.raises(InputError, match="测量序号重复"):
        read_transfer_sheet(book)
