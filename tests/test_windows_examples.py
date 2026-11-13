# SPDX-License-Identifier: Apache-2.0
"""随包案例、独立数值复算与可见布局。"""

import json
import math
import statistics
import subprocess
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document
from openpyxl import load_workbook
from scipy.stats import f, t

from openpt.io.validation import inspect_input
from openpt.windows_app import run_workbook, summarize

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "windows" / "examples"


def _algorithm_a(values: list[float]) -> tuple[float, float]:
    x = statistics.median(values)
    s = 1.483 * statistics.median(abs(v - x) for v in values)
    for iteration in range(1000):
        clipped = [min(max(v, x - 1.5 * s), x + 1.5 * s) for v in values]
        nx = statistics.mean(clipped)
        ns = 1.134 * statistics.stdev(clipped)
        quantum = Decimal(1).scaleb(Decimal(str(ns)).adjusted() - 2)
        stable = all(
            Decimal(str(a)).quantize(quantum) == Decimal(str(b)).quantize(quantum)
            for a, b in ((x, nx), (s, ns))
        )
        x, s = nx, ns
        if stable and iteration > 0:
            return x, 1.25 * s / math.sqrt(len(values))
    raise AssertionError("算法 A 未收敛")


@pytest.mark.parametrize("name", ["金属材料抗拉强度", "粉末振实密度", "数字多用表"])
def test_examples_independent_recalculation(name: str, tmp_path: Path) -> None:
    path = EXAMPLES / f"{name}.xlsx"
    assert inspect_input(path) == []
    directory, data, result = run_workbook(path, tmp_path)
    assert json.loads((directory / "result.json").read_text(encoding="utf-8")) == result
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
    text = summarize(data, result)
    doc = Document(directory / "report.docx")
    doc_text = "\n".join(p.text for p in doc.paragraphs)
    assigned = result["指定值与不确定度"]
    assert assigned["status"] == "OK" and "指定值" in doc_text and "指定值" in text
    if name == "数字多用表":
        assert "不适用样品间均匀性检验" in text and "不适用样品间均匀性检验" in doc_text
        configs = list(book["传递标准配置"].values)[1:]
        observations = list(book["传递标准复测"].values)[1:]
        for standard, point, unit, window, raw_rules, *_ in configs:
            values = [Decimal(str(row[5])) for row in observations if row[:2] == (standard, point)]
            delta = max(values) - min(values)
            rule = json.loads(raw_rules)[0]
            limit = Decimal(str(rule["value"])) / Decimal(str(rule.get("k", 1)))
            actual = result["传递标准稳定性"][f"{standard}|{point}"]
            assert actual["delta_max"] == pytest.approx(float(delta))
            assert actual["criteria"][0]["limit"] == pytest.approx(float(limit))
            assert actual["conclusion"] == (delta < limit)
            assert point in text and point in doc_text and unit in text and window == "all"
        key = f"{configs[0][0]}|{configs[0][1]}"
        values = [Decimal(str(row[5])) for row in observations if row[1] == configs[0][1]]
        expected = (values[0] + values[-1]) / 2
        assert assigned["value"] == pytest.approx(float(expected))
        assert assigned["u"] == pytest.approx(0.00004)
        for row in list(book["参加者结果"].values)[1:]:
            score = result["参加者统计量"][row[0]]["En"]
            en = (row[1] - float(expected)) / math.hypot(
                row[4], 2 * assigned["u"], 2 * result["传递标准稳定性"][key]["delta_max"]
            )
            assert score["status"] == "OK" and score["value"] == pytest.approx(en)
        assert "8.0000250" in doc_text
        return

    groups: dict[str, list[Decimal]] = defaultdict(list)
    for row in list(book["均匀性"].values)[1:]:
        groups[row[0]].append(Decimal(str(row[2])))
    data_groups = list(groups.values())
    n, m = len(data_groups), len(data_groups[0])
    means = [sum(row) / m for row in data_groups]
    grand = sum(means) / n
    ssb = sum(m * (mean - grand) ** 2 for mean in means)
    ssw = sum(
        (value - mean) ** 2 for row, mean in zip(data_groups, means, strict=True) for value in row
    )
    msb, msw = ssb / (n - 1), ssw / (n * (m - 1))
    calc_f = float(msb / msw)
    calc_ss = math.sqrt(max(0, float((msb - msw) / m)))
    hom = result["均匀性"]
    assert hom["F"] == pytest.approx(calc_f)
    assert hom["Ss"] == pytest.approx(calc_ss)
    assert hom["F_critical"] == pytest.approx(f.ppf(0.95, n - 1, n * (m - 1)))
    assert hom["conclusion"] == (calc_f < hom["F_critical"])
    periods: dict[str, dict[str, list[Decimal]]] = defaultdict(lambda: defaultdict(list))
    for row in list(book["稳定性"].values)[1:]:
        periods[row[0]][row[1]].append(Decimal(str(row[3])))
    samples = [
        [float(sum(row) / len(row)) for row in periods[group].values()]
        for group in ("基线", "稳定期")
    ]
    a, b = samples
    df = len(a) + len(b) - 2
    pooled = ((len(a) - 1) * statistics.variance(a) + (len(b) - 1) * statistics.variance(b)) / df
    calc_t = abs(statistics.mean(a) - statistics.mean(b)) / math.sqrt(
        pooled * (1 / len(a) + 1 / len(b))
    )
    stab = result["稳定性"]
    assert stab["t"] == pytest.approx(calc_t)
    assert stab["critical"] == pytest.approx(t.ppf(0.975, df))
    assert stab["pass"] == (calc_t < stab["critical"])
    participants = [row[1] for row in list(book["参加者结果"].values)[1:]]
    x, u = _algorithm_a(participants)
    assert assigned["value"] == pytest.approx(x) and assigned["u"] == pytest.approx(u)
    assert "GL003 4.2 F检验" in text and "稳定期" in text and "算法A稳健公议" in text
    assert "均匀性" in doc_text and "稳定性" in doc_text


def test_visible_package_layout(tmp_path: Path) -> None:
    target = tmp_path / "能力验证样品评价与定值工具"
    subprocess.run(
        [sys.executable, str(ROOT / "windows" / "prepare_examples.py"), str(target)], check=True
    )
    original = (ROOT / "windows" / "甲醛示例.xlsx").read_bytes()
    assert (target / "甲醛示例.xlsx").read_bytes() == original
    assert (target / "示例案例" / "甲醛示例.xlsx").read_bytes() == original
    assert {p.stem for p in (target / "示例案例").glob("*.xlsx")} == {
        "甲醛示例",
        "数字多用表",
        "金属材料抗拉强度",
        "粉末振实密度",
    }
    index = (target / "示例案例" / "案例说明.txt").read_text(encoding="utf-8")
    assert "数字湿度计" not in index and "直流电能表" not in index
    workflow = (ROOT / ".github/workflows/windows-build.yml").read_text(encoding="utf-8")
    assert "windows/prepare_examples.py" in workflow
    assert "能力验证样品评价与定值工具" in workflow and "OPENPT_GUI_SMOKE_SOURCE" in workflow
    assert "数字多用表.xlsx" in workflow and "数字湿度计.xlsx" not in workflow
