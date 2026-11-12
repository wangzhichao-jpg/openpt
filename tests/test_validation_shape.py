# SPDX-License-Identifier: Apache-2.0
"""导入与只读检查共享最小样本和重复数规则。"""

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given, settings
from hypothesis import strategies as st
from openpyxl import load_workbook

from openpt.cli import calculate
from openpt.io.excel import read_workbook, template
from openpt.io.validation import _check_rows, inspect_input


def test_stability_sample_count_and_balance() -> None:
    rows = [
        ["时间组", "单元编号", "重复编号", "值", "单位"],
        ["一", "A", 1, 1.0, "mg"],
        ["二", "B", 1, 1.0, "mg"],
        ["二", "B", 2, 1.0, "mg"],
        ["二", "C", 1, 1.0, "mg"],
    ]
    issues = _check_rows("稳定性", rows, [], {})
    assert any(i.category == "INSUFFICIENT_SAMPLES" and i.cell == "D2" for i in issues)
    assert any(i.category == "UNBALANCED_REPEATS" and i.cell == "D3" for i in issues)


@given(
    st.lists(
        st.lists(st.one_of(st.none(), st.integers(-20, 20)), min_size=1, max_size=3),
        min_size=1,
        max_size=4,
    )
)
@settings(max_examples=25, deadline=None)
def test_random_homogeneity_workbooks_validate_before_calculate(
    groups: list[list[int | None]],
) -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "input.xlsx"
        template(path)
        book = load_workbook(path)
        book["项目信息"]["B2"] = "测试"
        book["项目信息"]["B3"] = "mg"
        for unit, values in enumerate(groups):
            for repeat, value in enumerate(values):
                book["均匀性"].append([unit + 1, repeat + 1, value, "mg"])
        book.save(path)
        book.close()
        if not inspect_input(path):
            calculate(read_workbook(path))
