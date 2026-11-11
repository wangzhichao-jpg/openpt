# SPDX-License-Identifier: Apache-2.0
"""使用虚构输入验证复核命令的主要分支。"""

import csv
from pathlib import Path

from openpt.cli import main


def test_synthetic_review_cli(tmp_path: Path) -> None:
    """合成示例：技术重复、模型切换、中间值修约和合成标准差。"""
    source = Path(__file__).parents[1] / "examples" / "synthetic_review.xlsx"
    report, result, diff = (tmp_path / n for n in ("r.docx", "r.json", "d.csv"))
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
            ]
        )
        == 0
    )
    with diff.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    categories = {item for row in rows for item in row["差异类型"].split("|")}
    assert {
        "PSEUDO_REPLICATION",
        "MODEL_SWITCH",
        "ROUNDING_INTERMEDIATE",
        "SIGMA_COMPOSITE",
        "VALUE_MISMATCH",
        "NOT_REPRODUCIBLE",
    } <= categories
