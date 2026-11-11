# SPDX-License-Identifier: Apache-2.0
"""外部授权材料的复核入口测试。"""

import csv
import json
import os
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn

from openpt.cli import main

pytestmark = pytest.mark.internal


def _run_case(tmp_path: Path, name: str) -> list[dict[str, str]]:
    directory = os.environ.get("OPENPT_INTERNAL_DIR")
    if not directory:
        pytest.skip("未设置内部材料目录")
    fixtures = Path(directory) / "fixtures"
    index = json.loads((fixtures / "fixture_index.json").read_text(encoding="utf-8"))
    source = fixtures / index[name]
    report, result, diff = (tmp_path / n for n in ("review.docx", "result.json", "diff.csv"))
    assert (
        main(
            [
                "review",
                str(source),
                "--docx",
                str(report),
                "--json",
                str(result),
                "--differences",
                str(diff),
                "--mapping",
                str(Path(directory) / "mappings" / "mapping.json"),
            ]
        )
        == 0
    )
    with diff.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_u09_stability_review(tmp_path: Path) -> None:
    """输入及声称值的原始页码见外部 fixtures/来源说明.md。"""
    rows = _run_case(tmp_path, "case_b")
    z = [r for r in rows if r["统计量"].startswith("z:")]
    assert len(z) == 141 and all(r["显示一致"] == "True" for r in z)
    assert any(
        r["统计量"] == "Ss"
        and "CRITERION_EXCEEDED" in r["差异类型"]
        and "合成为 σ′" in r["说明"]
        and r["状态"] == "NOTE"
        for r in rows
    )
    tests = [r for r in rows if r["统计量"] == "t"]
    assert len(tests) == 2 and all("PSEUDO_REPLICATION" in r["差异类型"] for r in tests)
    assert "MODEL_SWITCH" in tests[1]["差异类型"]
    assert all(r["状态"] == "NOTE" and "VALUE_MISMATCH" not in r["差异类型"] for r in tests)
    assert all("VALUE_MISMATCH" not in r["差异类型"] for r in rows if r["显示一致"] == "True")
    designs = [r for r in rows if r["差异类型"] == "DESIGN_WARNING"]
    assert len(designs) == 2 and all("3 个包装单元" in r["说明"] for r in designs)
    assert all("5.2.2" in r["说明"] and "条目3" in r["评分条目"] for r in designs)
    assert any("SIGMA_COMPOSITE" in r["差异类型"] and "报告使用合成" in r["说明"] for r in rows)
    assert all(r["显示一致"] == "True" for r in rows if r["统计量"] in ("x*", "s*"))
    assert any(r["统计量"] == "s*" and r["推荐一致"] == "False" for r in rows)


def test_u10_run_stop_rule_sensitivity(tmp_path: Path) -> None:
    """内部统计样的默认规则及绝对容差收敛对照。"""
    directory = os.environ.get("OPENPT_INTERNAL_DIR")
    if not directory:
        pytest.skip("未设置内部材料目录")
    fixtures = Path(directory) / "fixtures"
    index = json.loads((fixtures / "fixture_index.json").read_text(encoding="utf-8"))
    source = fixtures / index["case_b"]
    report, result = tmp_path / "run.docx", tmp_path / "run.json"
    assert main(["run", str(source), "--docx", str(report), "--json", str(result)]) == 0
    values = json.loads(result.read_text(encoding="utf-8"))
    assert values["算法A"]["rule"] == "gl002" and values["算法A"]["iterations"] == 7
    assert values["算法A_收敛对照"]["rule"] == "absolute"
    assert values["算法A_收敛对照"]["converged"]
    assert round(values["算法A"]["s"], 2) == 3.62
    assert round(values["算法A_收敛对照"]["s"], 2) == 3.63
    assert any("停止规则敏感" in paragraph.text for paragraph in Document(report).paragraphs)


def test_u11_participant_review(tmp_path: Path) -> None:
    """内部统计样附表的参与者及报告显示值，来源见仓库外夹具。"""
    rows = _run_case(tmp_path, "case_b")
    z = [r for r in rows if r["统计量"].startswith("z:")]
    assert len(z) == 141 and all(r["显示一致"] == "True" for r in z)
    assert all(r["显示一致"] == "True" for r in rows if r["统计量"] in ("x*", "s*"))
    sensitive = next(r for r in rows if r["统计量"] == "s*")
    assert sensitive["状态"] == "NOTE" and "STOP_RULE_SENSITIVITY" in sensitive["差异类型"]
    assert "VALUE_MISMATCH" not in sensitive["差异类型"]
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["算法A"]["rule"] == "gl002" and result["算法A"]["iterations"] == 7
    assert result["算法A_收敛对照"]["converged"] is True
    assert round(result["算法A"]["s"], 2) == 3.62
    assert round(result["算法A_收敛对照"]["s"], 2) == 3.63
    doc = Document(tmp_path / "review.docx")
    assert any("停止规则敏感" in p.text for p in doc.paragraphs)
    score_table = next(table for table in doc.tables if table.cell(0, 0).text == "参加者")
    assert len(score_table.rows) == 142
    assert score_table.rows[0]._tr.get_or_add_trPr().find(qn("w:tblHeader")) is not None


def test_u12_participant_review(tmp_path: Path) -> None:
    """输入及声称值的原始页码见外部 fixtures/来源说明.md。"""
    rows = _run_case(tmp_path, "case_a")
    assert any("ROUNDING_INTERMEDIATE" in r["差异类型"] for r in rows)
    assert any(r["统计量"] == "s1" and "VALUE_MISMATCH" in r["差异类型"] for r in rows)
    assert any(
        r["统计量"] == "z:03"
        and "VALUE_MISMATCH" in r["差异类型"]
        and r["状态"] == "DIFFERENCE"
        and "待底稿确认" in r["说明"]
        for r in rows
    )
    assert all(r["显示一致"] == "True" for r in rows if r["统计量"] in ("x*", "s*"))
