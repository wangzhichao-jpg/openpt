# SPDX-License-Identifier: Apache-2.0
"""随包案例的输入、独立复算、报告与可见布局。"""

import json
import math
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document
from openpyxl import load_workbook

from openpt.io.validation import inspect_input
from openpt.windows_app import run_workbook, summarize

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "windows" / "examples"


@pytest.mark.parametrize("name", ["数字湿度计", "数字多用表", "直流电能表"])
def test_examples_independent_recalculation(name: str, tmp_path: Path) -> None:
    """不调用统计内核：直接从表格算极差、限值、参考均值和 En。"""
    path = EXAMPLES / f"{name}.xlsx"
    assert inspect_input(path) == []
    directory, data, result = run_workbook(path, tmp_path)
    disk_result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    assert disk_result == result
    book = load_workbook(path, data_only=True)
    assert not book.defined_names and not book._external_links
    assert all(sheet.sheet_state == "visible" and not sheet._images for sheet in book)
    assert not any(
        cell.comment or cell.hyperlink for sheet in book for row in sheet for cell in row
    )
    with ZipFile(path) as archive:
        assert not any(
            marker in item.lower()
            for item in archive.namelist()
            for marker in ("comment", "externallink", "media/", "vml")
        )
        assert b"creator" not in archive.read("docProps/core.xml")
    configs = list(book["传递标准配置"].values)[1:]
    observations = list(book["传递标准复测"].values)[1:]
    text = summarize(data, result)
    doc = Document(directory / "report.docx")
    doc_text = "\n".join(p.text for p in doc.paragraphs)
    assert "不适用样品间均匀性检验" in text
    assert "不适用样品间均匀性检验" in doc_text
    for standard, point, unit, window, raw_rules, *_ in configs:
        values = [
            Decimal(str(row[5]))
            for row in observations
            if row[0] == standard
            and row[1] == point
            and (window == "all" or row[4] in ("传递中", "传递后"))
        ]
        delta = max(values) - min(values)
        rule = json.loads(raw_rules)[0]
        limit = Decimal(str(rule["value"])) / Decimal(str(rule.get("k", 1)))
        actual = result["传递标准稳定性"][f"{standard}|{point}"]
        assert actual["delta_max"] == pytest.approx(float(delta))
        assert actual["criteria"][0]["limit"] == pytest.approx(float(limit))
        assert actual["conclusion"] == (delta < limit)
        assert point in text and point in doc_text and "限值" in text and unit in text
    assigned = result["指定值与不确定度"]
    assert assigned["status"] == "OK" and "指定值" in doc_text and "指定值" in text
    ref_point = configs[0][1]
    ref_values = [Decimal(str(row[5])) for row in observations if row[1] == ref_point]
    expected = (
        ref_values[0]
        if name == "数字湿度计"
        else (ref_values[-1] + ref_values[-2 if name == "直流电能表" else 0]) / 2
    )
    assert assigned["value"] == pytest.approx(float(expected))
    assert assigned["u"] == pytest.approx(
        {"数字湿度计": 0.16, "数字多用表": 0.00004, "直流电能表": 0.06}[name]
    )
    if name == "数字多用表":
        point = result["传递标准稳定性"][f"{configs[0][0]}|{ref_point}"]
        for row in list(book["参加者结果"].values)[1:]:
            score = result["参加者统计量"][row[0]]["En"]
            expected_en = (row[1] - float(expected)) / math.hypot(
                row[4], 2 * assigned["u"], 2 * point["delta_max"]
            )
            assert score["status"] == "OK" and score["value"] == pytest.approx(expected_en)
        assert "8.0000250" in doc_text


def test_visible_package_layout(tmp_path: Path) -> None:
    target = tmp_path / "能力验证样品评价与定值工具"
    subprocess.run(
        [sys.executable, str(ROOT / "windows" / "prepare_examples.py"), str(target)], check=True
    )
    original = (ROOT / "windows" / "甲醛示例.xlsx").read_bytes()
    assert (target / "甲醛示例.xlsx").read_bytes() == original
    assert (target / "示例案例" / "甲醛示例.xlsx").read_bytes() == original
    assert len(list((target / "示例案例").glob("*.xlsx"))) == 4
    assert (target / "示例案例" / "案例说明.txt").is_file()
    workflow = (ROOT / ".github/workflows/windows-build.yml").read_text(encoding="utf-8")
    assert "windows/prepare_examples.py" in workflow
    assert "能力验证样品评价与定值工具" in workflow and "OPENPT_GUI_SMOKE_SOURCE" in workflow
