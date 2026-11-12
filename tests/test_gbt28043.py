# SPDX-License-Identifier: Apache-2.0
"""附录 B 的公开合成数据、边界和内部例题测试。"""

import csv
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from docx import Document
from openpyxl import load_workbook
from scipy.stats import chi2, f

from openpt.cli import calculate
from openpt.core.gbt28043 import homogeneity, stability
from openpt.errors import InputError
from openpt.io.excel import read_workbook, template
from openpt.report.docx import make_report
from openpt.review.compare import review


def test_homogeneity_basic_and_repeatability() -> None:
    data = [[float(i), float(i)] for i in range(10)]
    h = homogeneity(data, 10)
    assert h["sx"] == pytest.approx(math.sqrt(110 / 12))
    assert h["sw"] == 0
    assert h["ss"] == pytest.approx(h["sx"])
    assert h["basic_pass"] is False
    assert h["repeatability_check"] is True
    assert h["f1"] == pytest.approx(chi2.ppf(0.95, 9) / 9)
    assert h["f2_or_fm"] == pytest.approx((f.ppf(0.95, 9, 10) - 1) / 2)
    assert h["extended_pass"] is True


def test_homogeneity_zero_and_outside_table() -> None:
    result = homogeneity([[0, 2], [0, 2]], 1)
    assert result["variance_raw"] < 0
    assert result["ss"] == 0
    assert result["basic_pass"] is True
    assert result["repeatability_check"] is False
    assert result["extended_pass"] is None
    assert homogeneity([[0, 0]] * 21, 1)["f1"] is None
    assert homogeneity([[0, 0]] * 10, None)["basic_pass"] is None
    with pytest.raises(InputError):
        homogeneity([[1, 2], [3]], 1)


def test_homogeneity_multiple_repeats() -> None:
    result = homogeneity([[float(i), float(i + 1), float(i + 2)] for i in range(10)], 5)
    assert result["f2_or_fm"] == pytest.approx(f.ppf(0.95, 9, 20) / 3)


def test_stability_boundaries_and_independence() -> None:
    a = [[0, 0], [0, 0]]
    b = [[0.3, 0.3], [0.3, 0.3]]
    assert stability(a, b, 1)["basic_pass"] is True
    b = [[0.31, 0.31], [0.31, 0.31]]
    r = stability(a, b, 1, u1=0.01, u2=0.01)
    assert r["basic_pass"] is False and r["extended_pass"] is True
    assert stability(a, b, 1, independent=False)["basic_pass"] is None
    assert stability(a, b, None)["extended_pass"] is None
    with pytest.raises(InputError):
        stability(a, b, 1, u1=-1)


def test_template_and_workflow(tmp_path: Path) -> None:
    path = tmp_path / "data.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "合成"
    book["项目信息"]["B3"] = "mg"
    book["方法配置"]["B3"] = 2
    book["方法配置"]["B21"] = "gbt28043"
    book["方法配置"]["B22"] = 0.1
    book["方法配置"]["B23"] = 0.2
    book["方法配置"]["B24"] = "gl003"
    assert any("B21" in str(v.sqref) for v in book["方法配置"].data_validations.dataValidation)
    for i in range(10):
        for j in range(2):
            book["均匀性"].append([str(i), str(j), i + j / 10, "mg"])
    for group, shift in (("基线", 0), ("稳定期", 0.1)):
        for i in range(3):
            for j in range(2):
                book["稳定性"].append([group, str(i), str(j), i + j / 10 + shift, "mg"])
    book.save(path)
    data = read_workbook(path)
    result = calculate(data)
    assert result["标准模式"] == "gbt28043"
    assert result["GB/T均匀性"]["basic_pass"] is False
    assert result["GB/T稳定性"]["稳定期"]["extended_limit"] is not None
    data["claims"] = [
        {"name": "均匀性基本限值", "value": 0.6, "digits": 3, "source": "合成", "model": "gl003"}
    ]
    rows = review(data, result)
    assert any(row["差异类型"] == "STANDARD_MODE" for row in rows)
    claimed = next(row for row in rows if row["统计量"] == "均匀性基本限值")
    assert claimed["显示一致"] and claimed["推荐一致"]
    target = tmp_path / "report.docx"
    make_report(target, data, result)
    text = "\n".join(p.text for p in Document(target).paragraphs)
    assert "GB/T 28043-2019 标准模式（主评价）" in text
    assert "GL003 计算仅为参考" in text


@pytest.mark.r
@pytest.mark.parametrize("m", [2, 3])
def test_r_independent(tmp_path: Path, m: int) -> None:
    rscript = shutil.which("Rscript")
    if not rscript:
        pytest.skip("Rscript 不可用")
    x = [[float(i) + j / 10 for j in range(m)] for i in range(10)]
    y = [[1.0, 1.1], [1.2, 1.3]]
    paths = [tmp_path / "x.csv", tmp_path / "y.csv"]
    for path, values in zip(paths, (x, y), strict=True):
        path.write_text(
            "\n".join(",".join(map(str, row)) for row in values) + "\n", encoding="utf-8"
        )
    script = Path(__file__).resolve().parents[1] / "validation/r/gbt28043.R"
    process = subprocess.run(
        [rscript, str(script), str(paths[0]), str(paths[1]), "2", ".1", ".2"],
        check=True,
        capture_output=True,
        text=True,
    )
    values = {
        row["statistic"]: float(row["value"]) for row in csv.DictReader(process.stdout.splitlines())
    }
    h, s = homogeneity(x, 2), stability(x, y, 2, u1=0.1, u2=0.2)
    for rkey, key in (
        ("sx", "sx"),
        ("sw", "sw"),
        ("ss", "ss"),
        ("f1", "f1"),
        ("factor", "f2_or_fm"),
        ("c", "c"),
        ("extended_limit", "extended_limit"),
    ):
        assert values[rkey] == pytest.approx(h[key], rel=1e-10, abs=1e-12)
    assert values["difference"] == pytest.approx(s["difference"])
    assert values["stability_limit"] == pytest.approx(s["extended_limit"])


@pytest.mark.internal
def test_internal_e2() -> None:
    root = os.environ.get("OPENPT_INTERNAL_DIR")
    if not root:
        pytest.skip("未设置内部材料目录")
    fixture = json.loads((Path(root) / "fixtures/gbt28043/e2.json").read_text(encoding="utf-8"))
    x = fixture["homogeneity"]
    sigma = sum(sum(row) for row in x) / sum(map(len, x)) * fixture["sigma_fraction_of_baseline"]
    h = homogeneity(x, sigma)
    s = stability(x, fixture["stability"], sigma)
    printed = fixture["printed"]
    for key, target in (("mean", "mean"), ("sx", "mean_sd"), ("sw", "sw"), ("ss", "ss")):
        assert h[key] == pytest.approx(printed[target], abs=0.0000051)
    assert s["mean2"] == pytest.approx(printed["followup_mean"], abs=0.0000051)
    assert s["difference"] == pytest.approx(printed["difference"], abs=0.0000051)
    assert h["basic_pass"] is printed["homogeneity_pass"]
    assert s["basic_pass"] is printed["stability_pass"]
