# SPDX-License-Identifier: Apache-2.0
"""参数枚举、模板及手册使用同一份代码清单。"""

import subprocess
import sys
from pathlib import Path

from openpyxl import load_workbook

from openpt.config.catalog import (
    CLAIM_NAMES,
    ENUMS,
    HOMOGENEITY_CLAIM_NAMES,
    REPORT_MODELS,
    markdown,
    template_rows,
)
from openpt.io.excel import template

ROOT = Path(__file__).resolve().parents[1]


def test_manual_matches_generated_catalog() -> None:
    text = (ROOT / "docs/使用手册.md").read_text(encoding="utf-8")
    begin = "<!-- OPENPT-CATALOG-BEGIN -->\n"
    end = "\n<!-- OPENPT-CATALOG-END -->"
    assert text.split(begin, 1)[1].split(end, 1)[0] == markdown()
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools/generate_reference.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_template_catalog_and_dropdowns(tmp_path: Path) -> None:
    path = tmp_path / "template.xlsx"
    template(path)
    book = load_workbook(path)
    rows = {(str(row[0].value), str(row[1].value)) for row in book["填写说明"].iter_rows(min_row=2)}
    assert set(template_rows()).issubset(rows)
    assert {"F值", "方差分析F值", "均值差", "x̄", "ȳ"}.issubset(CLAIM_NAMES)
    assert HOMOGENEITY_CLAIM_NAMES.issubset(CLAIM_NAMES)
    assert {
        "recommended",
        "repeats_pooled",
        "repeats_welch",
        "displayed_summary",
        "absolute",
    } <= set(REPORT_MODELS)
    for cell, field in (
        ("B9", "algorithm_a_rule"),
        ("B12", "sigma_stage"),
        ("B13", "observation_level"),
        ("B14", "stability_design"),
        ("B21", "criterion_standard"),
    ):
        matches = [
            dv for dv in book["方法配置"].data_validations.dataValidation if cell in dv.cells
        ]
        assert len(matches) == 1
        assert matches[0].formula1 == '"' + ",".join(ENUMS[field]) + '"'
