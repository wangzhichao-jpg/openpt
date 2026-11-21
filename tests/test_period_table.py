# SPDX-License-Identifier: Apache-2.0
"""时间组表与 JSON 的一致性及定位。"""

import json
from pathlib import Path
from typing import Any

import pytest
from openpyxl import load_workbook

from openpt.cli import calculate
from openpt.config.field_labels import field_key
from openpt.errors import InputError, format_error
from openpt.io.excel import read_workbook, template
from openpt.io.period_table import FIELDS, HEADERS, SHEET, create_period_sheet
from openpt.io.validation import inspect_input
from openpt.windows_app import make_template, run_workbook

EXAMPLE = Path(__file__).resolve().parents[1] / "windows/examples/GB-T合成检测.xlsx"


def set_config(book: Any, field: str, value: Any) -> None:
    for row in book["方法配置"].iter_rows(min_row=2):
        if str(row[0].value).endswith(f"（{field}）"):
            row[1].value = value
            return
    book["方法配置"].append([field, value])


def sample() -> Any:
    book = load_workbook(EXAMPLE)
    ws = book["稳定性"]
    for row in list(ws.iter_rows(min_row=2, values_only=True)):
        if row[0] == "稳定期":
            ws.append(["运输期", *row[1:]])
    create_period_sheet(book)
    return book


def add_row(book: Any, name: str | int, **values: Any) -> None:
    book[SHEET].append([name, *[values.get(field) for field in FIELDS.values()]])


def test_table_json_and_merge_equivalence(tmp_path: Path) -> None:
    options = {
        "稳定期": {"rule": "basic"},
        "运输期": {"rule": "extended", "kind": "transport", "u2": 0.5},
    }
    books = [sample(), sample(), sample()]
    set_config(books[0], "stability_period_options", json.dumps(options, ensure_ascii=False))
    add_row(books[1], "稳定期", rule="basic")
    add_row(books[1], "运输期", rule="extended", kind="transport", u2=0.5)
    set_config(
        books[2],
        "stability_period_options",
        json.dumps({"运输期": {"kind": "transport"}}, ensure_ascii=False),
    )
    add_row(books[2], "稳定期", rule="basic")
    add_row(books[2], "运输期", rule="extended", u2=0.5)
    results = []
    snapshots = []
    for index, book in enumerate(books):
        set_config(book, "stability_u1", 0.5)
        path = tmp_path / f"{index}.xlsx"
        book.save(path)
        assert not inspect_input(path)
        results.append(calculate(read_workbook(path)))
        _, _, result = run_workbook(path, tmp_path / f"run{index}")
        snapshots.append(result)
    assert results[0] == results[1] == results[2]
    assert snapshots[0] == snapshots[1] == snapshots[2]


def test_numeric_group_name_matches_stability_data(tmp_path: Path) -> None:
    book = sample()
    for row in list(book["稳定性"].iter_rows(min_row=2, values_only=True)):
        if row[0] == "稳定期":
            book["稳定性"].append([7, *row[1:]])
    add_row(book, 7, rule="basic")
    path = tmp_path / "numeric-group.xlsx"
    book.save(path)
    assert not inspect_input(path)
    assert "7" in calculate(read_workbook(path))["GB/T稳定性"]


def test_mixed_method_and_baseline_across_json_and_table(tmp_path: Path) -> None:
    book = sample()
    set_config(book, "criterion_standard", "gl003")
    for row in book["指定值与不确定度"].iter_rows(min_row=2):
        if field_key(row[0].value) == "hom_source":
            row[1].value = "manual"
    set_config(
        book, "stability_period_options", '{"运输期":{"stability_method":"mean_difference"}}'
    )
    add_row(book, "运输期", baseline_source="homogeneity")
    path = tmp_path / "combined.xlsx"
    book.save(path)
    assert not inspect_input(path)
    _, _, result = run_workbook(path, tmp_path / "runs")
    assert result["其他稳定性"]["运输期"]["method"] == "mean_difference"
    assert result["其他稳定性"]["运输期"]["criterion_settings"]["baseline_source"] == {
        "value": "homogeneity",
        "source": "逐组设置",
    }


@pytest.mark.parametrize(
    ("case", "cell", "message"),
    [
        ("duplicate", "A3", "重复"),
        ("conflict", "C2", "JSON 重复"),
        ("unknown", "A2", "不存在"),
        ("enum", "C2", "rule"),
        ("number", "E2", "delta_e"),
        ("kind", "B2", "kind"),
        ("trend", "G2", "趋势法只能全局设置"),
        ("missing_baseline", "G2", "须明确登记"),
    ],
)
def test_errors_located_and_consistent(tmp_path: Path, case: str, cell: str, message: str) -> None:
    book = sample()
    if case in ("trend", "missing_baseline"):
        set_config(book, "criterion_standard", "gl003")
    if case == "duplicate":
        add_row(book, "稳定期", rule="basic")
        add_row(book, "稳定期", rule="extended")
    elif case == "conflict":
        set_config(book, "stability_period_options", '{"稳定期":{"rule":"basic"}}')
        add_row(book, "稳定期", rule="extended")
    elif case == "unknown":
        add_row(book, "第九天", rule="basic")
    elif case == "enum":
        add_row(book, "稳定期", rule="bad")
    elif case == "number":
        add_row(book, "稳定期", delta_e=-1)
    elif case == "kind":
        add_row(book, "稳定期", kind="bad")
    elif case == "trend":
        add_row(book, "稳定期", stability_method="regression_trend")
    else:
        add_row(book, "稳定期", stability_method="mean_difference")
    path = tmp_path / "error.xlsx"
    book.save(path)
    issues = inspect_input(path)
    matching = [i for i in issues if i.sheet == SHEET and i.cell == cell and message in i.message]
    assert matching, issues
    with pytest.raises(InputError) as exc:
        calculate(read_workbook(path))
    assert any(
        i.get("sheet") == SHEET and i.get("cell") == cell and message in i.get("message", "")
        for i in exc.value.issues
    )
    assert f"『{SHEET}』第{cell[1:]}行" in format_error(exc.value)


def test_templates_and_fill(tmp_path: Path) -> None:
    path = tmp_path / "template.xlsx"
    template(path)
    book = load_workbook(path)
    ws = book[SHEET]
    assert [c.value for c in ws[1]] == HEADERS
    validations = ws.data_validations.dataValidation
    assert len(validations) == 5
    assert all(v.allow_blank for v in validations)
    assert {str(v.sqref) for v in validations} == {
        "B2:B1048576",
        "C2:C1048576",
        "D2:D1048576",
        "G2:G1048576",
        "H2:H1048576",
    }
    assert {v.formula1 for v in validations} == {
        '"storage,transport"',
        '"basic,extended"',
        '"sigma_pt,delta_e"',
        '"one_sample,two_sample,mean_difference"',
        '"homogeneity,baseline_group"',
    }
    source = sample()
    for name in ("项目信息", "均匀性", "稳定性"):
        for row in source[name].iter_rows(min_row=2, values_only=True):
            book[name].append(row)
    # 项目信息模板本来有空行，在原位置填充。
    book["项目信息"]["B2"] = "合成项目"
    book["项目信息"]["B3"] = "mg/L"
    unit = source["项目信息"]["B3"].value
    book["项目信息"]["B3"] = unit
    set_config(book, "sigma", 10)
    set_config(book, "criterion_standard", "gbt28043")
    set_config(book, "stability_u1", 0.5)
    add_row(book, "运输期", rule="extended", kind="transport", u2=0.5)
    book.save(path)
    _, _, result = run_workbook(path, tmp_path / "run")
    assert result["GB/T稳定性"]["运输期"]["selected_rule"] == "extended"
    gui = tmp_path / "gui.xlsx"
    make_template(gui)
    assert SHEET in load_workbook(gui).sheetnames
