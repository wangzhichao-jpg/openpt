# SPDX-License-Identifier: Apache-2.0
"""固定种子的抽样、盲码和检测次序。"""

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from openpyxl import load_workbook

from openpt.cli import main
from openpt.errors import InputError
from openpt.sampling import _allocation, sample, write_sample


def test_strata_reproducible_and_independent_repeats(tmp_path: Path) -> None:
    """每层按比例抽样，盲码置换，两次重复进入随机顺序。"""
    groups = {"大层": list(range(1, 81)), "小层": list(range(81, 101))}
    result = sample(100, 20, 12345, groups)
    assert result == sample(100, 20, 12345, groups)
    assert result["allocation"] == {"大层": 16, "小层": 4}
    assert len({x["盲码"] for x in result["samples"]}) == 20
    assert len({(x["单元编号"], x["重复编号"]) for x in result["tests"]}) == 40
    assert "独立取样" in result["note"]
    assert not result["warnings"]
    assert sample(20, 9, 2)["warnings"][0].startswith("DESIGN_WARNING")
    output = tmp_path / "output"
    assert (
        main(["sample", "--units", "20", "--pick", "10", "--seed", "9", "--output", str(output)])
        == 0
    )
    assert load_workbook(output / "sample.xlsx").active.max_row == 21
    assert (
        main(["sample", "--units", "20", "--pick", "10", "--seed", "9", "--output", str(output)])
        == 2
    )
    with pytest.raises(InputError, match="完整覆盖"):
        sample(3, 2, 4, {"层": [1, 1, 3]})


def test_spreadsheet_formula_injection(tmp_path: Path) -> None:
    """用户提供的层名在 XLSX 和 CSV 中不作为公式执行。"""
    output = tmp_path / "safe"
    write_sample(output, sample(2, 2, 1, {"=1+1": [1, 2]}))
    sheet = load_workbook(output / "sample.xlsx").active
    assert sheet["C2"].data_type == "s"
    assert "'=1+1" in (output / "sample.csv").read_text(encoding="utf-8-sig")


@given(st.lists(st.integers(min_value=1, max_value=100), min_size=1, max_size=10), st.data())
def test_allocation_bounds(sizes: list[int], data: st.DataObject) -> None:
    """任意有效分层均满足总数、下限和容量。"""
    n = data.draw(st.integers(min_value=len(sizes), max_value=sum(sizes)))
    counts = _allocation(sizes, n)
    assert sum(counts) == n
    assert all(1 <= count <= size for count, size in zip(counts, sizes, strict=True))
