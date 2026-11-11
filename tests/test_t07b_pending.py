# SPDX-License-Identifier: Apache-2.0
"""未评价事项及人工复核提示。"""

from pathlib import Path

from docx import Document
from hypothesis import given
from hypothesis import strategies as st

from openpt.report.docx import _unevaluated, make_report


def test_unevaluated_and_report(tmp_path: Path) -> None:
    """报告列出状态、原因，且不自动放行。"""
    result = {
        "均匀性": {"Ss_status": "NOT_EVALUATED", "warnings": ["缺少 σ"]},
        "稳定性": {"status": "DESIGN_REVIEW", "design_warnings": ["相关设计"]},
    }
    path = tmp_path / "report.docx"
    make_report(path, {"info": {}, "config": {}}, result={"其他": result})
    doc = Document(path)
    text = "\n".join(p.text for p in doc.paragraphs)
    table_text = "\n".join(
        cell.text for table in doc.tables for row in table.rows for cell in row.cells
    )
    assert "待人工复核" in text and "不自动放行" in text
    assert "未提供用于用途判据的 σ" in table_text and "相关设计" in table_text
    assert _unevaluated(result) == [
        ("结果.均匀性.Ss_status", "NOT_EVALUATED", "未提供用于用途判据的 σ"),
        ("结果.稳定性.status", "DESIGN_REVIEW", "相关设计"),
    ]


@given(st.sampled_from(["NOT_EVALUATED", "DESIGN_REVIEW", "UNASSESSED"]))
def test_nested_status_is_not_lost(status: str) -> None:
    """嵌套列表中的指定状态仍进入清单。"""
    assert _unevaluated({"a": [{"status": status}]}) == [
        ("结果.a[0].status", status, "结果未记录具体原因，需人工核查")
    ]
