# SPDX-License-Identifier: Apache-2.0
"""三格式与决定绑定、HTML 和 XLSX 安全。"""

import hashlib
import json
import math
from pathlib import Path

from docx import Document
from openpyxl import load_workbook

from openpt.cli import main
from openpt.demo import _a1
from openpt.runs import verify_directory


def test_formats_decisions_and_security(tmp_path: Path) -> None:
    """报告关键数值来自相同结果，用户内容不可注入。"""
    path = tmp_path / "input.xlsx"
    _a1(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "<script>alert(1)</script>"
    book.save(path)
    runs = tmp_path / "runs"
    assert main(["run", str(path), "--runs-dir", str(runs)]) == 0
    root = next(runs.iterdir())
    result_bytes = (root / "result.json").read_bytes()
    result = json.loads(result_bytes)
    doc = Document(root / "report.docx")
    paragraphs = [p.text for p in doc.paragraphs]
    start = paragraphs.index("全精度结果") + 1
    end = paragraphs.index("附录：原始数据及单元格来源")
    doc_result = json.loads("\n".join(paragraphs[start:end]))
    assert doc_result == result
    html = (root / "report.html").read_text(encoding="utf-8")
    assert "<script>" not in html and "&lt;script&gt;" in html
    workbook = load_workbook(root / "report.xlsx", data_only=False)
    values = list(workbook["全精度数值"].values)
    for key in ("F", "F_critical", "mean", "MS_within", "Ss"):
        number = result["均匀性"][key]
        row = next(row for row in values if row[0] == f"结果.均匀性.{key}")
        assert math.isclose(row[1], number, rel_tol=1e-15, abs_tol=0)
        assert float(row[3]) == number and str(number) in html
    assert (
        main(
            [
                "decide",
                str(root),
                "--item",
                "均匀性",
                "--decision",
                "接受",
                "--by",
                "审核人",
                "--note",
                "=1+1",
            ]
        )
        == 0
    )
    record = json.loads((root / "decisions.jsonl").read_text(encoding="utf-8"))
    assert record["result_sha256"] == hashlib.sha256(result_bytes).hexdigest()
    assert verify_directory(root) == []
    assert main(["reproduce", str(root)]) == 0
    revision = Document(root / "report_rev_0001.docx")
    assert any(
        "=1+1" in cell.text for table in revision.tables for row in table.rows for cell in row.cells
    )
    revised = load_workbook(root / "report_rev_0001.xlsx", data_only=False)
    assert all(cell.data_type != "f" for ws in revised for row in ws for cell in row)
    assert (
        main(["decide", str(root), "--item", "均匀性", "--decision", "退回", "--by", "审核人"]) == 0
    )
    assert len((root / "decisions.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    assert (root / "report_rev_0001.docx").exists()
    assert (root / "report_rev_0002.docx").exists()
