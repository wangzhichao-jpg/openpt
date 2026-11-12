# SPDX-License-Identifier: Apache-2.0
"""内测 C 输入标识与输出隔离回归。"""

import hashlib
from pathlib import Path

import pytest
from docx import Document
from openpyxl import load_workbook
from test_transfer_workflow import _workbook

from openpt.cli import main
from openpt.io.new_stability import read_transfer_sheet
from openpt.io.validation import inspect_input


def test_transfer_identifiers(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    _workbook(path)
    book = load_workbook(path)
    sheet = book["传递标准复测"]
    for row in range(2, 6):
        sheet.cell(row, 4).value = None
    sheet.cell(2, 3).value = 10
    sheet.cell(3, 3).value = 2
    assert [r["order"] for r in read_transfer_sheet(book)] == ["2", "3", "4", "10"]
    for row, value in enumerate(("第十次", "第二次", "第一次", "第六次"), 2):
        sheet.cell(row, 3).value = value
    assert [r["order"] for r in read_transfer_sheet(book)] == [
        "第一次",
        "第二次",
        "第六次",
        "第十次",
    ]
    sheet.cell(2, 3).value = None
    sheet.cell(2, 4).value = "2025-01-01"
    assert read_transfer_sheet(book)[-1]["date"] == "2025-01-01"
    sheet.cell(2, 4).value = None
    with pytest.raises(ValueError, match="测量序号或日期必填"):
        read_transfer_sheet(book)
    book.save(path)
    assert inspect_input(path)


@pytest.mark.parametrize("command", ["run", "review"])
def test_outputs_stay_outside_input(
    tmp_path: Path, command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "input"
    source.mkdir()
    path = source / "input.xlsx"
    _workbook(path)
    book = load_workbook(path)
    for row in range(2, 6):
        book["传递标准复测"].cell(row, 4).value = None
    book.save(path)
    (source / "existing.txt").write_text("不得覆盖", encoding="utf-8")

    def snapshot() -> dict[str, str]:
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}

    before = snapshot()
    runs = tmp_path / "runs"
    assert main([command, str(path), "--runs-dir", str(runs)]) == 0
    assert snapshot() == before
    directory = next(runs.iterdir())
    text = capsys.readouterr().out
    assert str(directory / "report.docx") in text
    assert str(directory / "result.json") in text
    if command == "review":
        assert str(directory / "differences.csv") in text
    doc = Document(directory / "report.docx")
    assert any(
        "序号或日期" in cell.text
        for table in doc.tables
        for row in table.rows
        for cell in row.cells
    )
