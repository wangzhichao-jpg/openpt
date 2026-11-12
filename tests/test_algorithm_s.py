# SPDX-License-Identifier: Apache-2.0
"""GL002 附录 A.3 算法 S 独立解析算例。"""

import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from openpt.cli import main
from openpt.core.robust import algorithm_s
from openpt.errors import InputError
from openpt.io.excel import template


def test_constant_standard_deviations() -> None:
    """所有标准差均为 1，自由度为 1 时截尾不起作用，w*=1.097。"""
    result = algorithm_s([1, 1, 1, 1], 1)
    assert result.w == pytest.approx(1.097)
    assert result.converged and result.iterations >= 2
    assert result.eta == 1.645 and result.xi == 1.097
    assert len(result.history) == result.iterations


def test_zero_and_invalid_df() -> None:
    """全零尺度不可判定，GL002 表 A.1 只覆盖自由度 1 至 10。"""
    assert algorithm_s([0, 0], 1).status == "INDETERMINATE"
    with pytest.raises(InputError):
        algorithm_s([1, 2], 11)
    assert algorithm_s([1, 4], 1, max_iterations=1).status == "NOT_CONVERGED"


def test_algorithm_s_workbook(tmp_path: Path) -> None:
    """从模板输入算法 S 并导出迭代记录。"""
    path = tmp_path / "s.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "虚构"
    book["项目信息"]["B3"] = "mg/kg"
    book["算法S"].append([1, 1])
    book["算法S"].append([1, 1])
    book.save(path)
    assert (
        main(
            [
                "run",
                str(path),
                "--runs-dir",
                str(tmp_path / "runs"),
                "--json",
                str(tmp_path / "s_结果.json"),
            ]
        )
        == 0
    )
    result = json.loads((tmp_path / "s_结果.json").read_text(encoding="utf-8"))["算法S"]
    assert result["w"] == pytest.approx(1.097) and result["history"]
