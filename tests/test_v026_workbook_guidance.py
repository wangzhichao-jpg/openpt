# SPDX-License-Identifier: Apache-2.0
"""字段兼容、填写场景、即时提示与时间组类型。"""

import os
import subprocess
from pathlib import Path

import pytest
from docx import Document
from openpyxl import Workbook, load_workbook

from openpt.cli import calculate, main
from openpt.config.field_labels import ASSIGNED_LABELS, field_key, field_label
from openpt.config.workbook_guidance import SCENARIOS, scenario_markdown
from openpt.io.excel import read_workbook, template
from openpt.io.validation import inspect_input
from openpt.io.workbook_hints import CASE_SUFFIX, RELATIONS, SCENARIO_MARKER
from openpt.report.docx import make_report
from openpt.windows_app import make_template

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = [
    *sorted((ROOT / "windows/examples").glob("*.xlsx")),
    ROOT / "windows/甲醛示例.xlsx",
    *[
        p
        for p in sorted((ROOT / "examples").rglob("*.xlsx"))
        if not (p.parent.name == "trace_run" and p.name in {"report.xlsx", "report_rev_0001.xlsx"})
    ],
]


def set_value(book: Workbook, sheet: str, field: str, value: object) -> None:
    for row in book[sheet].iter_rows(min_row=2):
        if field_key(row[0].value) == field:
            row[1].value = value
            return
    book[sheet].append([field, value])


def basic_workbook(path: Path) -> Workbook:
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "最小场景合成"
    book["项目信息"]["B3"] = "mg"
    for i, value in enumerate([0.95, 0.98, 1.0, 1.02, 1.04, 1.08], 1):
        book["参加者结果"].append([f"P{i}", value, "mg"])
    for i in range(3):
        for j in range(2):
            value = 1.0 + i * 0.1 + j * 0.01
            book["均匀性"].append([str(i), str(j), value, "mg"])
            book["稳定性"].append(["基线", str(i), str(j), value, "mg"])
            book["稳定性"].append(["稳定期", str(i), str(j), value + 0.01, "mg"])
    for key, value in (
        ("method", "reference"),
        ("value", 1),
        ("uncertainty", 0.02),
        ("source", "实验室经评定值"),
        ("uncertainty_source", "独立不确定度预算"),
    ):
        set_value(book, "指定值与不确定度", key, value)
    return book


@pytest.mark.parametrize(
    "scenario",
    [
        "consensus_a",
        "consensus_median",
        "reference",
        "certified",
        "known_u",
        "known_components",
        "sigma_manual",
        "sigma_niqr",
        "sigma_algorithm_a",
        "sigma_made",
        "sigma_algorithm_s",
        "criterion_sigma_pt",
        "gl003",
        "gbt_ss",
        "periods",
    ],
)
def test_minimal_scenarios_run(tmp_path: Path, scenario: str) -> None:
    path = tmp_path / f"{scenario}.xlsx"
    book = basic_workbook(path)
    assigned = "指定值与不确定度"
    config = "方法配置"
    if scenario.startswith("consensus"):
        set_value(book, assigned, "method", "participant_consensus")
        set_value(book, assigned, "value", None)
        set_value(book, assigned, "uncertainty", None)
        set_value(
            book,
            assigned,
            "consensus_method",
            "median" if scenario.endswith("median") else "robust_mean",
        )
    elif scenario == "certified":
        set_value(book, assigned, "method", "certified")
    elif scenario.startswith("known"):
        set_value(book, assigned, "method", "known")
        if scenario == "known_components":
            set_value(book, assigned, "uncertainty", None)
            set_value(book, assigned, "known_components", "0.01,0.02")
    elif scenario == "sigma_manual":
        set_value(book, assigned, "sigma_final", 1)
        set_value(book, assigned, "sigma_procedure", "事先评定")
    elif scenario.startswith("sigma_"):
        method = scenario.removeprefix("sigma_")
        set_value(book, assigned, "sigma_pt_method", method)
        if method == "niqr":
            set_value(book, config, "quantile_method", "linear")
        if method == "algorithm_s":
            set_value(book, config, "algorithm_s_input_type", "standard_deviation")
            book["算法S"].append([0.1, 3])
            book["算法S"].append([0.2, 3])
    elif scenario == "criterion_sigma_pt":
        set_value(book, assigned, "sigma_final", 1)
        set_value(book, assigned, "sigma_procedure", "事先评定")
        set_value(book, config, "criterion_sigma_source", "sigma_pt")
    elif scenario == "gl003":
        set_value(book, config, "sigma", 1)
        set_value(book, config, "gl003_hom_criterion", "ss_0.3sigma")
    elif scenario == "gbt_ss":
        set_value(book, config, "criterion_standard", "gbt28043")
        set_value(book, config, "sigma", 1)
        set_value(book, assigned, "hom_source", "gbt_ss")
        set_value(book, assigned, "hom_mapping", "assigned")
    elif scenario == "periods":
        set_value(book, config, "criterion_standard", "gbt28043")
        set_value(book, config, "sigma", 1)
        for i in range(3):
            for j in range(2):
                book["稳定性"].append(["运输期", str(i), str(j), 1.01 + i * 0.1 + j * 0.01, "mg"])
        book["稳定性时间组配置"].append(["稳定期", "storage", "basic"])
        book["稳定性时间组配置"].append(["运输期", "transport", "basic"])
    needs_participants = scenario.startswith("consensus") or scenario in {
        "sigma_niqr",
        "sigma_algorithm_a",
        "sigma_made",
    }
    for sheet, needed in (
        ("参加者结果", needs_participants),
        ("均匀性", scenario in {"criterion_sigma_pt", "gl003", "gbt_ss"}),
        ("稳定性", scenario == "periods"),
    ):
        if not needed:
            book[sheet].delete_rows(2, book[sheet].max_row)
    book.save(path)
    assert inspect_input(path) == []
    data = read_workbook(path)
    result = calculate(data)
    assert result["指定值与不确定度"]["value"] is not None
    assert main(["run", str(path), "--runs-dir", str(tmp_path / "runs")]) == 0


def test_old_english_labels_are_compatible_and_errors_show_both(tmp_path: Path) -> None:
    source = tmp_path / "chinese.xlsx"
    book = basic_workbook(source)
    book.save(source)
    old = tmp_path / "legacy.xlsx"
    for row in book["指定值与不确定度"].iter_rows(min_row=2):
        row[0].value = field_key(row[0].value)
    book.save(old)
    assert calculate(read_workbook(old)) == calculate(read_workbook(source))
    assert inspect_input(old) == []
    set_value(book, "指定值与不确定度", "source", None)
    book.save(old)
    issue = next(i for i in inspect_input(old) if i.field == "source")
    assert "指定值来源说明（source）" in issue.message and issue.cell == "B5"
    with pytest.raises(ValueError, match="指定值来源说明（source）") as error:
        calculate(read_workbook(old))
    assert "B5" in str(error.value)
    set_value(book, "指定值与不确定度", "source", "实验室经评定值")
    set_value(book, "方法配置", "alpha", -1)
    book.save(old)
    assert any("显著性水平（alpha）" in item.message for item in inspect_input(old))


def test_field_prompts_examples_and_scenarios(tmp_path: Path) -> None:
    assert len(EXAMPLES) == 19
    template_path = tmp_path / "template.xlsx"
    template(template_path)
    window_template = tmp_path / "gui-template.xlsx"
    make_template(window_template)
    docs = (ROOT / "docs/使用手册.md").read_text(encoding="utf-8")
    assert scenario_markdown() in docs
    for path in [template_path, window_template, *EXAMPLES]:
        book = load_workbook(path)
        instructions = book["填写说明"]
        cases = [row for row in instructions.iter_rows(min_row=2) if row[0].value == "本案例"]
        if path in (template_path, window_template):
            assert not cases
        else:
            assert all(CASE_SUFFIX in str(row[1].value) for row in cases)
        assert any(row[0].value == SCENARIO_MARKER for row in instructions.iter_rows(min_row=2))
        for title, description in SCENARIOS:
            assert any(
                row[0].value == title and row[1].value == description
                for row in instructions.iter_rows(min_row=2)
            )
        for name in ("方法配置", "指定值与不确定度"):
            ws = book[name]
            validations = ws.data_validations.dataValidation
            for row in ws.iter_rows(min_row=2):
                if not row[0].value:
                    continue
                matches = [dv for dv in validations if row[1].coordinate in dv.sqref]
                assert len(matches) == 1, (path, name, row[1].coordinate)
                dv = matches[0]
                assert dv.showInputMessage and dv.prompt and len(dv.prompt) <= 255
                assert "含义：" in dv.prompt and "允许：" in dv.prompt and "关联：" in dv.prompt
                assert field_key(row[0].value) in RELATIONS
                assert len(dv.promptTitle) <= 32
                if name == "指定值与不确定度":
                    key = field_key(row[0].value)
                    assert row[0].value == field_label(key) and key in ASSIGNED_LABELS
            assert len(ws.conditional_formatting) > 0
        assert not book.defined_names and not book._external_links


def test_stability_group_types_always_shown(tmp_path: Path) -> None:
    path = tmp_path / "periods.xlsx"
    book = basic_workbook(path)
    set_value(book, "方法配置", "sigma", 1)
    for i in range(3):
        for j in range(2):
            book["稳定性"].append(["运输期", str(i), str(j), 1.01 + i * 0.1 + j * 0.01, "mg"])
    book["稳定性时间组配置"].append(["运输期", "transport"])
    book.save(path)
    data = read_workbook(path)
    result = calculate(data)
    report = tmp_path / "report.docx"
    make_report(report, data, result)
    doc = Document(report)
    table = next(
        t for t in doc.tables if [c.text for c in t.rows[0].cells] == ["时间组", "类型", "类型来源"]
    )
    assert {tuple(c.text for c in row.cells) for row in table.rows[1:]} == {
        ("稳定期", "储存稳定性", "默认"),
        ("运输期", "运输稳定性", "逐组设置"),
    }
    # 不显式登记 transport 时，即使名称是运输期也不能擅自推断。
    book["稳定性时间组配置"].delete_rows(2)
    book.save(path)
    data = read_workbook(path)
    make_report(report, data, calculate(data))
    table = next(
        t
        for t in Document(report).tables
        if [c.text for c in t.rows[0].cells] == ["时间组", "类型", "类型来源"]
    )
    assert any(
        [c.text for c in row.cells] == ["运输期", "储存稳定性", "默认"] for row in table.rows[1:]
    )


def test_libreoffice_roundtrip(tmp_path: Path) -> None:
    soffice = os.environ.get("OPENPT_TEST_SOFFICE")
    if not soffice:
        pytest.skip("未配置带 Calc 的 LibreOffice（OPENPT_TEST_SOFFICE）")
    path = tmp_path / "template.xlsx"
    template(path)
    output = tmp_path / "converted"
    output.mkdir()
    proc = subprocess.run(
        [
            soffice,
            f"-env:UserInstallation={(tmp_path / 'profile').as_uri()}",
            "--headless",
            "--convert-to",
            "xlsx",
            "--outdir",
            str(output),
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert proc.returncode == 0 and (output / path.name).is_file(), proc.stdout + proc.stderr
    book = load_workbook(output / path.name)
    for name in ("方法配置", "指定值与不确定度"):
        ws = book[name]
        assert ws.data_validations.dataValidation and ws.conditional_formatting
        assert all(dv.showInputMessage and dv.prompt for dv in ws.data_validations.dataValidation)
        assert any(
            "INDIRECT" in formula
            for rules in ws.conditional_formatting._cf_rules.values()
            for rule in rules
            for formula in rule.formula
        )
    for enabled in (True, False):
        book = load_workbook(path)
        values = [
            ("指定值与不确定度", "hom_source", "gbt_ss" if enabled else "manual"),
            ("方法配置", "criterion_standard", "gl003"),
            ("指定值与不确定度", "hom_mapping", "none"),
            ("指定值与不确定度", "u_hom", 2),
            ("指定值与不确定度", "sigma_pt_method", "niqr" if enabled else "manual"),
            ("指定值与不确定度", "sigma_final", 2),
            ("指定值与不确定度", "sigma_temporary", 2),
            ("方法配置", "criterion_sigma_source", "sigma_pt" if enabled else "manual"),
            ("方法配置", "sigma", 1),
            ("方法配置", "quantile_method", None),
        ]
        for sheet, key, value in values:
            set_value(book, sheet, key, value)
        counts = {}
        for name in ("方法配置", "指定值与不确定度"):
            ws = book[name]
            formulas = list(
                dict.fromkeys(
                    formula
                    for rules in ws.conditional_formatting._cf_rules.values()
                    for rule in rules
                    for formula in rule.formula
                )
            )
            counts[name] = len(formulas)
            for index, formula in enumerate(formulas, 1):
                ws.cell(index, 6, "=" + formula)
        test_path = tmp_path / ("conflict.xlsx" if enabled else "valid.xlsx")
        book.save(test_path)
        proc = subprocess.run(
            [
                soffice,
                f"-env:UserInstallation={(tmp_path / 'profile').as_uri()}",
                "--headless",
                "--convert-to",
                "xlsx",
                "--outdir",
                str(output),
                str(test_path),
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert proc.returncode == 0 and (output / test_path.name).is_file(), proc.stderr
        evaluated = load_workbook(output / test_path.name, data_only=True)
        for name, count in counts.items():
            assert all(
                evaluated[name].cell(index, 6).value is enabled for index in range(1, count + 1)
            )
