# SPDX-License-Identifier: Apache-2.0
"""算法 S 的停止规则与敏感性对照。"""

import json
from decimal import Decimal, localcontext
from pathlib import Path

import pytest
from docx import Document
from openpyxl import load_workbook

from openpt.cli import main
from openpt.core.robust import algorithm_s
from openpt.io.excel import template


@pytest.mark.parametrize(
    ("values", "df", "iterations", "expected", "reference"),
    [
        ([0.1, 0.12, 0.11, 0.5, 0.09], 1, 9, 0.17432539327551405, 0.17545164988445344),
        ([0.21, 0.25, 0.19, 0.8, 0.22, 0.24], 3, 5, 0.26734412666461044, 0.26760406970907552),
    ],
)
def test_gl002_sensitivity(
    values: list[float], df: int, iterations: int, expected: float, reference: float
) -> None:
    """GL002 A.3：验收样例的相邻两次迭代规则和绝对容差对照。"""
    result = algorithm_s(values, df)
    assert result.iterations == iterations and result.w == pytest.approx(expected, abs=1e-14)
    assert result.reference_converged and result.reference_w == pytest.approx(reference, abs=1e-12)
    assert result.warnings == ["STOP_RULE_SENSITIVITY"]
    absolute = algorithm_s(values, df, stop_rule="absolute", tolerance=1e-12)
    assert absolute.w == pytest.approx(reference, abs=5e-12) and not absolute.warnings
    loose = algorithm_s(values, df, stop_rule="absolute", tolerance=0.01)
    assert loose.iterations < absolute.iterations
    assert loose.reference_w == pytest.approx(reference, abs=1e-12)
    assert "STOP_RULE_SENSITIVITY" in loose.warnings


def test_reference_convergence_at_small_scale() -> None:
    """小量级时固定绝对容差可能过早停止；对照仍须满足相对收敛。"""
    values = [0.1, 0.12, 0.11, 0.5, 0.09]
    normal = algorithm_s(values, 1)
    small = algorithm_s([x * 1e-16 for x in values], 1)
    assert small.reference_converged and small.reference_iterations > 2
    assert small.reference_w == pytest.approx(normal.reference_w * 1e-16, rel=1e-10, abs=0.0)
    assert "STOP_RULE_SENSITIVITY" in small.warnings


def test_three_independent_hand_iterations() -> None:
    """对第一个算例手算三次：四个未截尾平方和 0.0446，第五项截断。"""
    result = algorithm_s([0.1, 0.12, 0.11, 0.5, 0.09], 1)
    with localcontext() as ctx:
        ctx.prec = 40
        w = Decimal("0.11")
        for index in range(3):
            w = (
                Decimal("1.097")
                * ((Decimal("0.0446") + (Decimal("1.645") * w) ** 2) / Decimal(5)).sqrt()
            )
            assert result.history[index]["w"] == pytest.approx(float(w), abs=1e-14)


def test_sensitivity_in_calculation_book(tmp_path: Path) -> None:
    """模板、JSON 和 DOCX 均保留选定值、对照值和敏感性警告。"""
    source = tmp_path / "s.xlsx"
    template(source)
    book = load_workbook(source)
    book["项目信息"]["B2"] = "虚构"
    book["项目信息"]["B3"] = "mg/kg"
    for value in [0.1, 0.12, 0.11, 0.5, 0.09]:
        book["算法S"].append([value, 1])
    book.save(source)
    assert main(["run", str(source)]) == 0
    result = json.loads((tmp_path / "s_结果.json").read_text(encoding="utf-8"))["算法S"]
    assert result["warnings"] == ["STOP_RULE_SENSITIVITY"]
    assert result["reference_converged"] and result["reference_iterations"] > result["iterations"]
    doc = Document(tmp_path / "s_计算书.docx")
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "STOP_RULE_SENSITIVITY" in text and "0.17432539" in text and "0.17545165" in text
