# SPDX-License-Identifier: Apache-2.0
"""计算书摘要、未评价提示及附录位置。"""

from pathlib import Path

from docx import Document

from openpt.cli import calculate
from openpt.report.docx import _decision_time, make_report


def test_unprovided_data_and_appendix(tmp_path: Path) -> None:
    path = tmp_path / "report.docx"
    make_report(path, {"info": {}, "config": {}}, {"示例": {"value": 1.23456789}})
    doc = Document(path)
    paragraphs = [p.text for p in doc.paragraphs]
    text = "\n".join(paragraphs)
    assert paragraphs[0] == "计算结论（须经人工复核签字）"
    assert "未提供稳定性数据，本次未评价稳定性" in text
    assert "不会被评价，请确认没有应评而未填的项目" in text
    assert "放行" not in text
    assert paragraphs.index("附录：原始数据及单元格来源") > paragraphs.index("人工复核")
    appendix = next(p for p in doc.paragraphs if p.text == "附录：全精度记录")
    assert appendix.paragraph_format.page_break_before is True
    assert '  "示例": {' in paragraphs
    assert '    "value": 1.23456789' in paragraphs
    code = doc.paragraphs[paragraphs.index('    "value": 1.23456789')]
    assert code.paragraph_format.space_before.pt == 0
    assert code.paragraph_format.space_after.pt == 0
    assert code.paragraph_format.line_spacing == 1.0


def test_provenance_two_up_keeps_every_value(tmp_path: Path) -> None:
    path = tmp_path / "sources.docx"
    data = {
        "info": {},
        "config": {},
        "sources": ["均匀性!C2", "均匀性!C3"],
        "numeric_sources": {"均匀性!C2": 1.2, "均匀性!C3": 1.3, "配置!B2": 0.2},
    }
    make_report(path, data, {})
    cells = [
        cell.text for table in Document(path).tables for row in table.rows for cell in row.cells
    ]
    assert all(
        value in cells for value in ("均匀性!C2", "均匀性!C3", "配置!B2", "1.2", "1.3", "0.2")
    )


def test_gbt_summary_and_section_order(tmp_path: Path) -> None:
    data = {
        "info": {},
        "config": {"criterion_standard": "gbt28043", "sigma": 1.0},
        "homogeneity": [[1.0, 1.1], [1.2, 1.3], [1.4, 1.5]],
        "stability": {
            "基线": [[1.0, 1.1], [1.2, 1.3], [1.4, 1.5]],
            "稳定期": [[1.1, 1.2], [1.3, 1.4], [1.5, 1.6]],
        },
        "participants": [],
        "claims": [],
    }
    result = calculate(data)
    path = tmp_path / "gbt.docx"
    make_report(path, data, result)
    paragraphs = [p.text for p in Document(path).paragraphs]
    assert "GB/T 28043-2019 B.2.2" in paragraphs[1]
    assert "GB/T 28043-2019 B.5.1" in paragraphs[2]
    assert paragraphs.index("方法与配置") < paragraphs.index("均匀性方差分析")
    assert paragraphs.index("均匀性方差分析") < paragraphs.index("GB/T 28043-2019 稳定性（主评价）")
    assert paragraphs.index("GB/T 28043-2019 稳定性（主评价）") < paragraphs.index("稳定性评价")
    assert (
        paragraphs.index("稳定性评价")
        < paragraphs.index("未评价事项")
        < paragraphs.index("人工复核")
    )


def test_decision_time() -> None:
    assert _decision_time("2026-11-12T15:04:05+08:00") == "2026-11-12 07:04:05 UTC"
    assert _decision_time("无时区原文") == "无时区原文"
