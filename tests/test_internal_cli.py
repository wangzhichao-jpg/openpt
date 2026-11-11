# SPDX-License-Identifier: Apache-2.0
"""外部授权材料的复核入口测试。"""

import csv
import os
from pathlib import Path

import pytest

from openpt.cli import main

pytestmark = pytest.mark.internal


def _run_case(tmp_path: Path, name: str) -> list[dict[str, str]]:
    directory = os.environ.get("OPENPT_INTERNAL_DIR")
    if not directory:
        pytest.skip("未设置内部材料目录")
    source = Path(directory) / "fixtures" / name
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
    rows = _run_case(tmp_path, "mvp2_b.xlsx")
    z = [r for r in rows if r["统计量"].startswith("z:")]
    assert len(z) == 141 and all(r["显示一致"] == "True" for r in z)
    assert any(r["统计量"] == "Ss" and "超过" in r["说明"] for r in rows)
    tests = [r for r in rows if r["统计量"] == "t"]
    assert len(tests) == 2 and all("PSEUDO_REPLICATION" in r["差异类型"] for r in tests)
    assert "MODEL_SWITCH" in tests[1]["差异类型"]
    assert any("SIGMA_COMPOSITE" in r["差异类型"] and "报告使用合成" in r["说明"] for r in rows)
    assert all(r["显示一致"] == "True" for r in rows if r["统计量"] in ("x*", "s*"))
    assert any(r["统计量"] == "s*" and r["推荐一致"] == "False" for r in rows)


def test_u11_participant_review(tmp_path: Path) -> None:
    """内部统计样附表的参与者及报告显示值，来源见仓库外夹具。"""
    rows = _run_case(tmp_path, "mvp2_b.xlsx")
    z = [r for r in rows if r["统计量"].startswith("z:")]
    assert len(z) == 141 and all(r["显示一致"] == "True" for r in z)
    assert all(r["显示一致"] == "True" for r in rows if r["统计量"] in ("x*", "s*"))
    assert any(r["统计量"] == "s*" and r["推荐一致"] == "False" for r in rows)


def test_u12_participant_review(tmp_path: Path) -> None:
    """输入及声称值的原始页码见外部 fixtures/来源说明.md。"""
    rows = _run_case(tmp_path, "mvp2_a.xlsx")
    assert any("ROUNDING_INTERMEDIATE" in r["差异类型"] for r in rows)
    assert any(r["统计量"] == "s1" and "VALUE_MISMATCH" in r["差异类型"] for r in rows)
    assert any(r["统计量"] == "z:03" and "VALUE_MISMATCH" in r["差异类型"] for r in rows)
    assert all(r["显示一致"] == "True" for r in rows if r["统计量"] in ("x*", "s*"))
