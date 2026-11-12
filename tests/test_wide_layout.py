# SPDX-License-Identifier: Apache-2.0
"""宽表识别、来源定位和长表一致性。"""

from pathlib import Path

import pytest
from openpyxl import load_workbook

from openpt.cli import calculate, main
from openpt.errors import InputError
from openpt.io.excel import read_workbook, template
from openpt.io.validation import inspect_input


def _make(path: Path, wide: bool) -> None:
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "合成"
    book["项目信息"]["B3"] = "mg"
    hom, stab = book["均匀性"], book["稳定性"]
    hom.delete_rows(1, hom.max_row)
    stab.delete_rows(1, stab.max_row)
    hom.append(
        ["单元编号", "测定1", "测定2", "单位"] if wide else ["单元编号", "重复编号", "值", "单位"]
    )
    stab.append(
        ["时间组", "单元编号", "测定1", "测定2", "单位"]
        if wide
        else ["时间组", "单元编号", "重复编号", "值", "单位"]
    )
    for i in range(1, 4):
        a, b = float(i), i + 0.1
        if wide:
            hom.append([str(i), a, b, "mg"])
        else:
            hom.append([str(i), 1, a, "mg"])
            hom.append([str(i), 2, b, "mg"])
        for group, shift in (("基线", 0.0), ("稳定期", 0.2)):
            if wide:
                stab.append([group, str(i), a + shift, b + shift, "mg"])
            else:
                stab.append([group, str(i), 1, a + shift, "mg"])
                stab.append([group, str(i), 2, b + shift, "mg"])
    book.save(path)


def test_wide_long_match_and_cli_reproduce(tmp_path: Path) -> None:
    long = tmp_path / "long.xlsx"
    wide = tmp_path / "wide.xlsx"
    _make(long, False)
    _make(wide, True)
    assert not inspect_input(wide)
    a, b = read_workbook(long), read_workbook(wide)
    assert a["homogeneity"] == b["homogeneity"]
    assert a["stability"] == b["stability"]
    assert calculate(a) == calculate(b)
    assert b["sources"][:2] == ["均匀性!B2", "均匀性!C2"]
    assert b["sources"][6:8] == ["稳定性!C2", "稳定性!D2"]
    assert not any(name.startswith("示例-") for name in b["numeric_sources"])
    assert main(["run", str(wide), "--runs-dir", str(tmp_path / "runs")]) == 0
    assert main(["reproduce", str(next((tmp_path / "runs").iterdir()))]) == 0


def test_wide_missing_formula_and_duplicate_location(tmp_path: Path) -> None:
    path = tmp_path / "wide.xlsx"
    _make(path, True)
    book = load_workbook(path)
    book["均匀性"]["C2"] = None
    book["稳定性"]["D2"] = "=1+1"
    book["均匀性"]["A2"] = "A"
    book["均匀性"]["A3"] = "A"
    book.save(path)
    issues = inspect_input(path)
    assert any(i.category == "MISSING" and i.sheet == "均匀性" and i.cell == "C2" for i in issues)
    assert any(
        i.category == "FORMULA_NO_CACHE" and i.sheet == "稳定性" and i.cell == "D2" for i in issues
    )
    assert any(
        i.category == "DUPLICATE" and i.sheet == "均匀性" and i.cell == "A3" and i.original == "A"
        for i in issues
    )
    with pytest.raises(InputError):
        read_workbook(path)


def test_explicit_layout_and_measurand_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "wide.xlsx"
    _make(path, True)
    book = load_workbook(path)
    for row in book["方法配置"].iter_rows(min_row=2):
        if "（layout）" in str(row[0].value):
            row[1].value = "long"
    book.save(path)
    with pytest.raises(InputError, match="长表"):
        inspect_input(path)
    with pytest.raises(InputError, match="长表"):
        read_workbook(path)
    for row in book["方法配置"].iter_rows(min_row=2):
        if "（layout）" in str(row[0].value):
            row[1].value = "wide"
    book.save(path)
    assert not inspect_input(path)
    assert read_workbook(path)["homogeneity"]
    book["均匀性"]["E1"] = "被测量"
    book["均匀性"]["E2"] = "甲"
    book.save(path)
    assert any(
        i.category == "UNSUPPORTED_MEASURAND" and i.cell == "E2" for i in inspect_input(path)
    )
    with pytest.raises(InputError, match="被测量"):
        read_workbook(path)


def test_wide_csv_and_missing_location(tmp_path: Path) -> None:
    path = tmp_path / "wide.csv"
    path.write_text("单元编号,测定1,测定2,单位\nA,1.0,1.1,mg\nB,2.0,2.1,mg\n", encoding="utf-8-sig")
    assert not inspect_input(path)
    data = read_workbook(path, unit="mg")
    assert data["homogeneity"] == [[1.0, 1.1], [2.0, 2.1]]
    assert data["sources"] == ["均匀性!B2", "均匀性!C2", "均匀性!B3", "均匀性!C3"]
    path.write_text("单元编号,测定1,测定2,单位\nA,1.0,,mg\nB,2.0,2.1,mg\n", encoding="utf-8-sig")
    assert any(issue.category == "MISSING" and issue.cell == "C2" for issue in inspect_input(path))
