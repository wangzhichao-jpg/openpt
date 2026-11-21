# SPDX-License-Identifier: Apache-2.0
"""缺少判据必要输入时给出可操作的根因和后果。"""

import json
from pathlib import Path
from typing import Any

import pytest
from openpyxl import load_workbook

from openpt.config.field_labels import field_key
from openpt.errors import InputError
from openpt.io.period_table import FIELDS, SHEET, create_period_sheet
from openpt.windows_app import friendly_error, run_workbook, summarize

EXAMPLE = Path(__file__).resolve().parents[1] / "windows/examples/GB-T合成检测.xlsx"


def set_config(book: Any, key: str, value: Any) -> None:
    for row in book["方法配置"].iter_rows(min_row=2):
        if str(row[0].value).endswith(f"（{key}）"):
            row[1].value = value
            return
    book["方法配置"].append([key, value])


def sample() -> Any:
    book = load_workbook(EXAMPLE)
    ws = book["稳定性"]
    for row in list(ws.iter_rows(min_row=2, values_only=True)):
        if row[0] == "稳定期":
            ws.append(["运输期", *row[1:]])
    create_period_sheet(book)
    return book


def add_period(book: Any, name: str, **values: Any) -> None:
    book[SHEET].append([name, *[values.get(field) for field in FIELDS.values()]])


def run(book: Any, tmp_path: Path) -> tuple[dict[str, Any], str]:
    path = tmp_path / "sample.xlsx"
    book.save(path)
    _, data, result = run_workbook(path, tmp_path / "runs")
    return result, summarize(data, result)


@pytest.mark.parametrize(
    ("u1", "u2", "missing", "present"),
    [
        (None, None, ("u1", "u2"), ()),
        (0.5, None, ("u2",), ("u1",)),
        (None, 0.5, ("u1",), ("u2",)),
        (0.0, 0.0, (), ("u1", "u2")),
    ],
)
def test_transport_extended_missing_inputs(
    tmp_path: Path, u1: Any, u2: Any, missing: tuple[str, ...], present: tuple[str, ...]
) -> None:
    book = sample()
    set_config(book, "stability_u1", u1)
    add_period(book, "运输期", kind="transport", rule="extended", u2=u2)
    result, text = run(book, tmp_path)
    roots = [
        d
        for d in result.get("诊断提示", [])
        if d["类型"] == "扩展判据未评价" and "运输期" in d["说明"]
    ]
    if not missing:
        assert not roots
        return
    assert len(roots) == 1 and roots[0]["层级"] == "根因"
    msg = roots[0]["说明"]
    assert "运输期" in msg and "扩展判据（逐组设置）" in msg
    assert "如不需要扩展判据，可改用 basic" in msg
    for field in missing:
        assert "缺少 " + field in msg
    for field in present:
        assert "缺少 " + field not in msg
    if "u1" in missing:
        assert "『方法配置』stability_u1" in msg
    if "u2" in missing:
        assert "『稳定性时间组配置』u2 列" in msg and "JSON 的 u2" in msg
        assert "stability_u2" not in msg
    consequence = next(d for d in result["诊断提示"] if d["类型"] == "统计量暂停")
    assert consequence["层级"] == "后果" and "pending" in consequence["说明"]
    assert result["诊断提示"].index(roots[0]) < result["诊断提示"].index(consequence)
    assert msg in text
    assert "稳定性（运输期）未评价；请检查数据及设计警告" not in text


def test_transport_extended_missing_sigma(tmp_path: Path) -> None:
    book = sample()
    set_config(book, "sigma", None)
    set_config(book, "stability_u1", 0.5)
    add_period(book, "运输期", kind="transport", rule="extended", u2=0.5)
    result, _ = run(book, tmp_path)
    msg = next(
        d["说明"]
        for d in result["诊断提示"]
        if d["类型"] == "扩展判据未评价" and "运输期" in d["说明"]
    )
    assert "扩展判据（逐组设置）" in msg and "『方法配置』sigma" in msg
    assert "缺少 u1" not in msg and "缺少 u2" not in msg


def test_group_delta_basis_not_misdiagnosed_as_missing_global_sigma(tmp_path: Path) -> None:
    book = sample()
    set_config(book, "sigma", None)
    set_config(book, "stability_u1", 0.5)
    add_period(book, "运输期", rule="extended", basis="delta_e", delta_e=50, u2=0.5)
    result, _ = run(book, tmp_path)
    specific = next(
        d["说明"]
        for d in result["诊断提示"]
        if d["类型"] == "扩展判据未评价" and "运输期" in d["说明"]
    )
    assert "δE 依据不适用" in specific and "缺少判据 sigma" not in specific
    assert not any(
        "稳定性（运输期）" in d["说明"] and "判据 sigma 未填写" in d["说明"]
        for d in result["诊断提示"]
    )


def test_delta_basis_does_not_support_stability_extension(tmp_path: Path) -> None:
    book = sample()
    set_config(book, "stability_u1", 0.5)
    add_period(book, "运输期", rule="extended", basis="delta_e", delta_e=50, u2=0.5)
    result, _ = run(book, tmp_path)
    msg = next(
        d["说明"]
        for d in result["诊断提示"]
        if d["类型"] == "扩展判据未评价" and "运输期" in d["说明"]
    )
    assert "δE 依据不适用 B.5.2" in msg and "basic" in msg
    assert "缺少 u1" not in msg and "缺少 u2" not in msg
    consequence = next(d["说明"] for d in result["诊断提示"] if d["类型"] == "统计量暂停")
    assert "上述判据问题导致稳定性未评价" in consequence and "pending" in consequence


def test_extended_correlated_design(tmp_path: Path) -> None:
    book = sample()
    set_config(book, "stability_design", "paired")
    set_config(book, "stability_u1", 0.5)
    add_period(book, "运输期", rule="extended", u2=0.5)
    result, _ = run(book, tmp_path)
    msg = next(
        d["说明"]
        for d in result["诊断提示"]
        if d["类型"] == "扩展判据未评价" and "运输期" in d["说明"]
    )
    assert "配对设计" in msg and "stability_design" in msg
    assert "缺少 u1" not in msg and "缺少 u2" not in msg


def test_global_extended_stable_u2_location(tmp_path: Path) -> None:
    book = sample()
    set_config(book, "gbt_stability_rule", "extended")
    set_config(book, "stability_u1", 0.5)
    result, _ = run(book, tmp_path)
    msg = next(
        d["说明"]
        for d in result["诊断提示"]
        if d["类型"] == "扩展判据未评价" and "稳定期" in d["说明"]
    )
    assert "扩展判据（全局设置）" in msg and "缺少 u2" in msg
    assert "『方法配置』stability_u2" in msg and "『稳定性时间组配置』u2 列" in msg


@pytest.mark.parametrize("problem", ["sigma", "sample_count", "delta_basis", "single"])
def test_homogeneity_extended_reason(tmp_path: Path, problem: str) -> None:
    book = sample()
    set_config(book, "gbt_hom_rule", "extended")
    if problem == "sigma":
        set_config(book, "sigma", None)
    elif problem == "sample_count":
        book["均匀性"].delete_rows(12, book["均匀性"].max_row - 11)
    elif problem == "delta_basis":
        set_config(book, "gbt_criterion_basis", "delta_e")
        set_config(book, "delta_e", 50)
    else:
        set_config(book, "replicate_type", "single")
        ws = book["均匀性"]
        for index in range(ws.max_row, 1, -1):
            if ws.cell(index, 2).value == 2:
                ws.delete_rows(index)
    result, _ = run(book, tmp_path)
    msg = next(
        d["说明"]
        for d in result["诊断提示"]
        if d["类型"] == "扩展判据未评价" and "均匀性" in d["说明"]
    )
    assert "扩展判据（全局设置）" in msg and "gbt_hom_rule" in msg and "basic" in msg
    assert {
        "sigma": "『方法配置』sigma",
        "sample_count": "表 B.1",
        "delta_basis": "δE 依据不适用",
        "single": "单测设计",
    }[problem] in msg


def test_single_delta_basis_not_misdiagnosed_as_missing_sigma(tmp_path: Path) -> None:
    book = sample()
    set_config(book, "gbt_hom_rule", "extended")
    set_config(book, "gbt_criterion_basis", "delta_e")
    set_config(book, "delta_e", 50)
    set_config(book, "sigma", None)
    set_config(book, "replicate_type", "single")
    ws = book["均匀性"]
    for index in range(ws.max_row, 1, -1):
        if ws.cell(index, 2).value == 2:
            ws.delete_rows(index)
    result, _ = run(book, tmp_path)
    msg = next(
        d["说明"]
        for d in result["诊断提示"]
        if d["类型"] == "扩展判据未评价" and "均匀性" in d["说明"]
    )
    assert "δE 依据不适用" in msg and "单测设计" in msg
    assert "缺少判据 sigma" not in msg


def test_unused_gbt_delta_config_does_not_block_gl003(tmp_path: Path) -> None:
    book = sample()
    set_config(book, "criterion_standard", "gl003")
    set_config(book, "gbt_criterion_basis", "delta_e")
    set_config(book, "delta_e", None)
    for row in book["指定值与不确定度"].iter_rows(min_row=2):
        if field_key(row[0].value) == "hom_source":
            row[1].value = "manual"
    add_period(book, "运输期", kind="transport")
    result, _ = run(book, tmp_path)
    assert result["其他稳定性"]["运输期"]["method"] == "two_sample"


@pytest.mark.parametrize("source", ["global", "json", "table"])
def test_delta_e_missing_location(tmp_path: Path, source: str) -> None:
    book = sample()
    if source == "global":
        set_config(book, "gbt_criterion_basis", "delta_e")
    elif source == "json":
        set_config(
            book,
            "stability_period_options",
            json.dumps({"运输期": {"basis": "delta_e"}}, ensure_ascii=False),
        )
    else:
        add_period(book, "运输期", basis="delta_e")
    with pytest.raises(InputError) as error:
        run(book, tmp_path)
    text = friendly_error(error.value)
    assert "delta_e" in text and "『方法配置』" in text
    assert "运输期" in text and "『稳定性时间组配置』" in text and "JSON" in text
    if source != "global":
        assert "逐组设置" in text
    else:
        assert "全局设置" in text and "稳定期" in text
    if source == "table":
        assert "『稳定性时间组配置』第2行（D2" in text
    elif source == "json":
        assert "stability_period_options" in text and "『方法配置』第" in text
