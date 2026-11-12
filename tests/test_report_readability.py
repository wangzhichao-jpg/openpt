# SPDX-License-Identifier: Apache-2.0
"""计算书摘要、未评价提示及附录位置。"""

from pathlib import Path

from docx import Document

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
    assert '  "示例": {' in paragraphs
    assert '    "value": 1.23456789' in paragraphs
    code = doc.paragraphs[paragraphs.index('    "value": 1.23456789')]
    assert code.paragraph_format.space_before.pt == 0
    assert code.paragraph_format.space_after.pt == 0
    assert code.paragraph_format.line_spacing == 1.0


def test_decision_time() -> None:
    assert _decision_time("2026-11-12T15:04:05+08:00") == "2026-11-12 07:04:05 UTC"
    assert _decision_time("无时区原文") == "无时区原文"
