# SPDX-License-Identifier: Apache-2.0
"""批量差异表输入列不得泄露本机目录。"""

from pathlib import Path

from openpyxl import load_workbook

from openpt.cli import main
from openpt.demo import _synthetic
from openpt.review.batch import _file_labels


def test_identical_names_and_reserved_label(tmp_path: Path) -> None:
    """同名输入自动编号，且不与本来含序号的文件名冲突。"""
    directory_a, directory_b = tmp_path / "private-a", tmp_path / "private-b"
    directory_a.mkdir()
    directory_b.mkdir()
    first = directory_a / "sample.xlsx"
    second = directory_b / "sample.xlsx"
    third = directory_b / "sample (1).xlsx"
    for path in (first, second, third):
        _synthetic(path)
    output = tmp_path / "summary.xlsx"
    assert main(["review-batch", str(first), str(second), str(third), "--output", str(output)]) == 0
    sheet = load_workbook(output)["差异总表"]
    labels = {row[2].value for row in list(sheet.rows)[1:]}
    assert labels == {"sample (2).xlsx", "sample (3).xlsx", "sample (1).xlsx"}
    assert sheet.auto_filter.ref
    for row in sheet.iter_rows():
        for cell in row:
            assert str(tmp_path) not in str(cell.value)
            assert str(directory_a) not in str(cell.value)
            assert str(directory_b) not in str(cell.value)


def test_case_insensitive_disambiguation() -> None:
    """跨平台文件名比较采用忽略大小写的唯一性规则。"""
    labels = _file_labels([Path("a/CASE.xlsx"), Path("b/case.xlsx"), Path("b/CASE (1).xlsx")])
    assert labels == ["CASE (2).xlsx", "case (3).xlsx", "CASE (1).xlsx"]
    assert len({label.casefold() for label in labels}) == 3
