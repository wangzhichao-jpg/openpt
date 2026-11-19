# SPDX-License-Identifier: Apache-2.0
"""规则全集与两个入口的一致性。"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook, load_workbook

from openpt.cli import calculate
from openpt.config.rules import RULE_CODES, RuleIssue
from openpt.errors import InputError
from openpt.io.excel import read_workbook
from openpt.io.validation import inspect_input

EXAMPLE = Path(__file__).resolve().parents[1] / "windows/examples/GB-T合成检测.xlsx"


def _set(book: Workbook, sheet: str, field: str, value: Any) -> None:
    for row in book[sheet].iter_rows(min_row=2):
        label = str(row[0].value)
        if label == field or label.endswith(f"（{field}）"):
            row[1].value = value
            return
    book[sheet].append([field, value])


def _case(*changes: tuple[str, str, Any]) -> Callable[[Workbook], None]:
    def modify(book: Workbook) -> None:
        for sheet, field, value in changes:
            _set(book, sheet, field, value)

    return modify


A = "指定值与不确定度"
M = "方法配置"
CASES: dict[str, Callable[[Workbook], None]] = {
    "ASSIGNED_ENUM": _case((A, "hom_source", "invalid")),
    "ASSIGNED_BOOL": _case((A, "hom_in_base", "invalid")),
    "DISPOSITION_REASON_TYPE": _case((A, "stability_disposition_reason", 1)),
    "SOURCE_REQUIRED": _case((A, "source", None)),
    "LIST_METHOD": _case((A, "known_components", "1,2")),
    "LIST_INVALID": _case((A, "expert_values", "bad")),
    "COMPONENT_CONFLICT": _case(
        (A, "method", "known"),
        (A, "value", 100),
        (A, "uncertainty", 1),
        (A, "known_components", "1,2"),
    ),
    "EXPERT_CONFLICT": _case(
        (A, "method", "expert_consensus"), (A, "expert_values", "1,2"), (A, "value", 100)
    ),
    "VALUE_REQUIRED": _case((A, "method", "known"), (A, "value", None), (A, "uncertainty", 1)),
    "UNCERTAINTY_REQUIRED": _case(
        (A, "method", "known"), (A, "value", 100), (A, "uncertainty", None)
    ),
    "ASSIGNED_NUMBER": _case((A, "u_stab", -1)),
    "ASSIGNED_NUMBER_NO_METHOD": _case((A, "method", None), (A, "u_stab", "bad")),
    "SIGMA_PROCEDURE": _case((A, "sigma_procedure", None)),
    "HOM_SS_MAPPING": _case((A, "hom_mapping", "none")),
    "HOM_SS_MANUAL": _case((A, "u_hom", 1)),
    "HOM_SS_STANDARD": _case((M, "criterion_standard", "gl003")),
    "CONFIG_BOOL": _case((M, "trend_plot", "invalid")),
    "CONFIG_ENUM": _case((M, "criterion_standard", "invalid")),
    "CONFIG_NUMBER": _case((M, "alpha", "invalid")),
    "ALPHA_RANGE": _case((M, "alpha", 2)),
    "CONFIG_POSITIVE": _case((M, "sigma", -1)),
    "DISPLAY_VALUE_DECIMALS": _case((M, "display_value_decimals", -1)),
    "PERIOD_OPTIONS": _case((M, "stability_period_options", '{"稳定期":{"kind":"bad"}}')),
    "TRANSFER_MAP": _case((M, "transfer_en_map", "{bad")),
    "DELTA_REQUIRED": _case((M, "gbt_criterion_basis", "delta_e"), (M, "delta_e", None)),
}


def _data_from_modified(book: Workbook) -> dict[str, Any]:
    """从有效示例读取数据，再按表格修改字段，避免读取器先行拒绝无效值。"""
    data = read_workbook(EXAMPLE)
    for sheet, key in ((M, "config"), (A, "assigned_config")):
        for row in book[sheet].iter_rows(min_row=2):
            label = str(row[0].value or "")
            if not label:
                continue
            field = label.rsplit("（", 1)[-1][:-1] if label.endswith("）") else label
            data[key][field] = row[1].value
    return data


def test_cases_cover_all_codes() -> None:
    assert set(CASES) == set(RULE_CODES)
    with pytest.raises(ValueError, match="未知规则代码"):
        RuleIssue("field", None, "问题", "要求", "建议", "UNREGISTERED")


@pytest.mark.parametrize("code", sorted(CASES))
def test_preflight_and_calculation_agree(tmp_path: Path, code: str) -> None:
    book = load_workbook(EXAMPLE)
    CASES[code](book)
    path = tmp_path / "input.xlsx"
    book.save(path)
    issues = [issue for issue in inspect_input(path) if issue.code == code]
    assert issues, code
    with pytest.raises(InputError) as error:
        calculate(_data_from_modified(book))
    problems = error.value.issues
    assert any(
        problem["code"] == code and problem["field"] == issues[0].field for problem in problems
    )
    assert {problem["code"] for problem in problems} <= set(RULE_CODES)


def test_same_field_different_codes_are_retained(tmp_path: Path) -> None:
    book = load_workbook(EXAMPLE)
    _set(book, A, "hom_mapping", "invalid")
    path = tmp_path / "same-field.xlsx"
    book.save(path)
    expected = {"ASSIGNED_ENUM", "HOM_SS_MAPPING"}
    assert expected <= {issue.code for issue in inspect_input(path) if issue.field == "hom_mapping"}
    with pytest.raises(InputError) as error:
        calculate(_data_from_modified(book))
    assert expected <= {p["code"] for p in error.value.issues if p["field"] == "hom_mapping"}


def test_reports_all_at_once(tmp_path: Path) -> None:
    book = load_workbook(EXAMPLE)
    codes = {"SOURCE_REQUIRED", "HOM_SS_MAPPING", "ALPHA_RANGE", "ASSIGNED_NUMBER"}
    for code in codes:
        CASES[code](book)
    path = tmp_path / "multiple.xlsx"
    book.save(path)
    assert codes <= {issue.code for issue in inspect_input(path)}
    with pytest.raises(InputError) as error:
        calculate(_data_from_modified(book))
    assert codes <= {problem["code"] for problem in error.value.issues}
