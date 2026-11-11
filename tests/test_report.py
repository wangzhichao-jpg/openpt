# SPDX-License-Identifier: Apache-2.0
"""公开示例的计算书与机器输出核对。"""

import json
from pathlib import Path

from docx import Document

from openpt.cli import main


def test_report_matches_json(tmp_path: Path) -> None:
    """GL003 A.1 表1、2：DOCX 中的 F 按四位有效数字显示。"""
    source = Path(__file__).parents[1] / "examples" / "GL003_A1.xlsx"
    report = tmp_path / "result.docx"
    output = tmp_path / "result.json"
    assert main(["run", str(source), "--docx", str(report), "--json", str(output)]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    document = Document(report)
    cells = [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    assert format(result["均匀性"]["F"], ".4g") in cells
    assert "F 临界值" in cells
