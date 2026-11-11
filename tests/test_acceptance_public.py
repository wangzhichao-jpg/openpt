# SPDX-License-Identifier: Apache-2.0
"""公开的逐项基准与端到端检查。"""

import json
from pathlib import Path

from docx import Document

from openpt.cli import main
from openpt.core.homogeneity import analyze

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures_public/gl003_cases.json").read_text(encoding="utf-8"))


def test_u01_gl003_a1() -> None:
    """GL003 附录 A.1 表1、2。"""
    result = analyze(CASES["A1"]["data"])
    assert round(result["F"], 2) == 1.17
    assert round(result["F_critical"], 2) == 3.02
    assert result["conclusion"]


def test_u02_gl003_a2() -> None:
    """GL003 附录 A.2 表3、4；F 为对同一表格的独立重算。"""
    result = analyze(CASES["A2"]["data"], sigma=1.1)
    assert round(result["Ss"], 3) == 0.292
    assert round(result["F"], 2) == 3.78
    assert result["Ss_pass"] and not result["conclusion"]
    assert not analyze(CASES["A2"]["data"], sigma=1.1, strict=True)["conclusion"]


def test_u03_negative_variance() -> None:
    """合成十组相同组均值与组内偏差。"""
    result = analyze([[9, 11]] * 10)
    assert result["F"] == 0 and result["variance_raw"] == -1 and result["Ss"] == 0


def test_u04_constant_matrix() -> None:
    """合成相同值使 F 为零除零。"""
    result = analyze([[10, 10]] * 10)
    assert result["F"] is None and result["status"] == "INDETERMINATE"
    json.dumps(result, allow_nan=False)


def test_u05_missing_sigma() -> None:
    """GL003 A.1 未指定评价标准差。"""
    result = analyze(CASES["A1"]["data"])
    assert result["Ss_status"] == "NOT_EVALUATED" and result["conclusion"]


def test_u06_small_design() -> None:
    """合成的少于 GL003 4.1 样品数要求的设计。"""
    result = analyze(CASES["A1"]["data"][:8])
    assert result["design_warnings"] and result["status"] == "OK"


def test_u07_public_equivalent() -> None:
    """公开侧用 GL003 A.1 和三重复合成设计覆盖均匀性。"""
    assert round(analyze(CASES["A1"]["data"])["F"], 2) == 1.17
    assert analyze([[1, 2, 3]] * 10)["F"] == 0


def test_u13_cli(tmp_path: Path) -> None:
    """公开合成复核模板驱动 CLI，保留完整文件链。"""
    template = tmp_path / "blank.xlsx"
    assert main(["template", str(template)]) == 0
    source = ROOT / "examples/synthetic_review.xlsx"
    doc, result, diff = (tmp_path / n for n in ("r.docx", "r.json", "diff.csv"))
    assert (
        main(
            [
                "review",
                str(source),
                "--docx",
                str(doc),
                "--json",
                str(result),
                "--differences",
                str(diff),
            ]
        )
        == 0
    )
    assert doc.exists() and result.exists() and diff.exists()


def test_u14_docx_structure(tmp_path: Path) -> None:
    """GL003 A.1 输出包含原始数据、结果表、附录与复核栏。"""
    source = ROOT / "examples/GL003_A1.xlsx"
    doc, result = tmp_path / "r.docx", tmp_path / "r.json"
    assert main(["run", str(source), "--docx", str(doc), "--json", str(result)]) == 0
    document = Document(doc)
    paragraphs = "\n".join(p.text for p in document.paragraphs)
    assert all(x in paragraphs for x in ("原始数据", "均匀性方差分析", "全精度记录", "复核人"))
    assert any("F 临界值" in c.text for t in document.tables for r in t.rows for c in r.cells)
