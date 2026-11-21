# SPDX-License-Identifier: Apache-2.0
"""算法 A 可复核过程及未选用判据的显示。"""

from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from openpt.cli import calculate
from openpt.core.robust import algorithm_a
from openpt.io.excel import read_workbook
from openpt.report.docx import make_report
from openpt.windows_app import summarize

ROOT = Path(__file__).resolve().parents[1]
VALUES = [0.407, 0.402, 0.397, 0.411, 0.388, 0.328]


def sample_data() -> dict:
    data = read_workbook(ROOT / "windows/examples/GB-T合成检测.xlsx")
    data["participants"] = [
        {"id": f"S{i}", "value": value, "source": f"合成!B{i}"} for i, value in enumerate(VALUES, 1)
    ]
    return data


def table_dict(table: object) -> dict:
    return {row.cells[0].text: row.cells[1].text for row in table.rows[1:]}


def test_gl002_iteration_and_report(tmp_path: Path) -> None:
    data = sample_data()
    result = calculate(data)
    a = result["算法A"]
    assert a["iterations"] == 9 and a["converged"]
    assert a["x"] == pytest.approx(0.39616, abs=1e-5)
    assert a["s"] == pytest.approx(0.01623, abs=1e-5)
    assert a["u_x"] == pytest.approx(0.008283, abs=1e-6)
    assert result["算法A_收敛对照"]["s"] == pytest.approx(0.01646, abs=1e-5)
    assert "算法A：迭代 9 次（GL002 停止规则）" in summarize(data, result)
    path = tmp_path / "report.docx"
    make_report(path, data, result)
    doc = Document(path)
    text = "\n".join(p.text for p in doc.paragraphs)
    for phrase in (
        "algorithm_a_rule=gl002",
        "连续两次迭代",
        "式 A.1、A.2",
        "式 A.3—A.6",
        "1.483",
        "1.134",
        "u(x*)=1.25·s*/√p",
        "7.7.3 式(6)",
        "完全收敛对照值",
        "0.016462313",
    ):
        assert phrase in text
    assert "本节结果仅供参考" not in text
    table = next(t for t in doc.tables if t.cell(0, 0).text == "迭代序号")
    assert len(table.rows) == 11
    assert [r.cells[0].text for r in table.rows[1:]] == ["初值", *map(str, range(1, 10))]
    assert table.cell(10, 5).text == "满足停止条件"
    assert table.cell(1, 4).text == "—"
    assert all(table.cell(i, 4).text == "1" for i in range(2, 11))
    for row in table.rows[1:]:
        assert float(row.cells[3].text) == pytest.approx(1.5 * float(row.cells[2].text), rel=1e-7)


def test_long_iteration_truncation_and_full_history(tmp_path: Path) -> None:
    data = sample_data()
    data["config"].update(algorithm_a_rule="absolute", algorithm_a_tolerance=1e-15)
    result = calculate(data)
    history = result["算法A"]["history"]
    assert len(history) > 23
    path = tmp_path / "long.docx"
    make_report(path, data, result)
    doc = Document(path)
    table = next(t for t in doc.tables if t.cell(0, 0).text == "迭代序号")
    assert [r.cells[0].text for r in table.rows[1:]] == [
        "初值",
        *map(str, range(1, 21)),
        "…",
        *map(str, range(len(history) - 2, len(history) + 1)),
    ]
    assert table.rows[-1].cells[-1].text == "满足停止条件"
    assert any(f"共迭代 {len(history)} 次" in p.text for p in doc.paragraphs)
    assert len(history) == result["算法A"]["iterations"]


@pytest.mark.parametrize("rule", ["gbt28043", "absolute", "simplified"])
def test_rule_descriptions_and_reference_only(rule: str, tmp_path: Path) -> None:
    data = sample_data()
    data["config"]["algorithm_a_rule"] = rule
    data["assigned_config"].update(method="reference", value=0.4, uncertainty=0.01)
    result = calculate(data)
    path = tmp_path / "rule.docx"
    make_report(path, data, result)
    doc = Document(path)
    text = "\n".join(p.text for p in doc.paragraphs)
    assert f"algorithm_a_rule={rule}" in text
    assert "本节结果仅供参考，未用于指定值" in text
    if rule == "simplified":
        assert result["算法A"]["iterations"] == 0 and "未进行迭代" in text
    assert "算法A：迭代" not in summarize(data, result)


@pytest.mark.parametrize("method", ["certified", "reference"])
def test_optional_criteria_and_spacing(method: str, tmp_path: Path) -> None:
    data = sample_data()
    data["assigned_config"].update(method=method, value=0.4, uncertainty=0.01)
    result = calculate(data)
    path = tmp_path / "optional.docx"
    make_report(path, data, result)
    doc = Document(path)
    all_text = "\n".join(
        [p.text for p in doc.paragraphs]
        + [c.text for t in doc.tables for r in t.rows for c in r.cells]
    )
    assert "未评价（未提供数据或无法计算）" not in all_text
    stable = next(
        t for t in doc.tables if any(r.cells[0].text == "基线均值标准不确定度" for r in t.rows)
    )
    rows = table_dict(stable)
    for name in ("基线均值标准不确定度", "后续均值标准不确定度", "扩展限值", "扩展判据"):
        assert rows[name] == "—"
    assert "—：未提供或未选用" in all_text
    body = list(doc.element.body)
    separators = [
        Paragraph(body[i], doc)
        for i in range(1, len(body) - 1)
        if body[i - 1].tag == body[i + 1].tag == qn("w:tbl")
        and body[i].tag == qn("w:p")
        and not Paragraph(body[i], doc).text
    ]
    assert separators and all(p.paragraph_format.space_after.pt >= 6 for p in separators)


def test_selected_but_unavailable_explains_why(tmp_path: Path) -> None:
    data = sample_data()
    data["config"]["gbt_stability_rule"] = "extended"
    result = calculate(data)
    path = tmp_path / "selected.docx"
    make_report(path, data, result)
    doc = Document(path)
    table = next(
        t for t in doc.tables if any(r.cells[0].text == "基线均值标准不确定度" for r in t.rows)
    )
    rows = table_dict(table)
    assert rows["基线均值标准不确定度"] == "未提供（扩展判据需要）"
    assert "缺少基线或后续均值标准不确定度" in rows["扩展判据"]
    assert "缺少基线或后续均值标准不确定度" in rows["主结论"]


def test_nonconverged_iteration_not_marked_as_stopped(tmp_path: Path) -> None:
    data = sample_data()
    data["config"]["algorithm_a_max_iterations"] = 2
    result = calculate(data)
    assert not result["算法A"]["converged"]
    path = tmp_path / "nonconverged.docx"
    make_report(path, data, result)
    doc = Document(path)
    table = next(t for t in doc.tables if t.cell(0, 0).text == "迭代序号")
    assert table.rows[-1].cells[-1].text == "—"


def test_unavailable_homogeneity_extended_reason(tmp_path: Path) -> None:
    data = sample_data()
    data["homogeneity"] = data["homogeneity"][:6]
    data["config"]["gbt_hom_rule"] = "extended"
    result = calculate(data)
    path = tmp_path / "hom.docx"
    make_report(path, data, result)
    doc = Document(path)
    table = next(t for t in doc.tables if any(r.cells[0].text == "扩展限值 √c" for r in t.rows))
    rows = table_dict(table)
    assert "样品数超出扩展判据系数表范围" in rows["主结论"]
    assert "样品数超出扩展判据系数表范围" in rows["扩展判据"]


def test_core_results_unchanged_by_report() -> None:
    a = algorithm_a(VALUES)
    assert len(a.history) == a.iterations == 9
    assert set(a.history[0]) == {"iteration", "x", "s"}
