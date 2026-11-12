# SPDX-License-Identifier: Apache-2.0
"""计算书摘要、未评价提示及附录位置。"""

from pathlib import Path

from docx import Document

from openpt.report.docx import make_report


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
