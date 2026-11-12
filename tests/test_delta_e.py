# SPDX-License-Identifier: Apache-2.0
"""GB/T 28043 δ_E 基本判据与指定值不确定度的合成测试。"""

import csv
import math
import shutil
import subprocess
from pathlib import Path

import pytest
from docx import Document
from openpyxl import load_workbook

from openpt.cli import calculate
from openpt.core.gbt28043 import criterion_limit, homogeneity, stability
from openpt.core.scores import performance_score
from openpt.errors import InputError
from openpt.io.excel import read_workbook, template
from openpt.report.docx import make_report
from openpt.review.compare import review


@pytest.mark.parametrize("factor,expected", [(0.999, True), (1.0, True), (1.001, False)])
def test_delta_basic_boundaries(factor: float, expected: bool) -> None:
    # 两个水平各五个样品，样品间标准差按样本标准差构造。
    v = 0.1 * factor * math.sqrt(9 / 10)
    x = [[-v, -v]] * 5 + [[v, v]] * 5
    h = homogeneity(x, None, delta_e=1.0)
    s = stability([[0.0, 0.0]] * 2, [[0.1 * factor] * 2] * 2, None, delta_e=1.0)
    assert h["basic_limit"] == s["basic_limit"] == pytest.approx(0.1)
    assert h["basic_pass"] is expected and s["basic_pass"] is expected
    assert h["criterion_basis"] == s["criterion_basis"] == "delta_e"
    assert h["extended_pass"] is None and s["extended_pass"] is None
    assert h["repeatability_check"] is None and s["repeatability_exceeded"] is None
    score = performance_score(
        "D", 0, 0, delta_e=1, criterion_basis="delta_e", u_assigned=0.1 * factor
    )
    assert bool(score.warnings) is (not expected or factor == 1.0)
    if score.warnings:
        assert "0.1δ_E" in score.warnings[0]


def test_basis_selection_and_input_validation() -> None:
    assert criterion_limit(None, None) == ("sigma_pt", None)
    assert criterion_limit(1, None) == ("sigma_pt", pytest.approx(0.3))
    assert criterion_limit(None, 2) == ("delta_e", pytest.approx(0.2))
    assert criterion_limit(1, 2, "delta_e") == ("delta_e", pytest.approx(0.2))
    assert criterion_limit(1, 2, "sigma_pt") == ("sigma_pt", pytest.approx(0.3))
    for sigma, delta, basis in (
        (1, 2, None),
        (None, 2, "sigma_pt"),
        (1, None, "delta_e"),
        (1, 2, "invalid"),
        (None, 0, None),
        (None, -1, None),
        (None, float("inf"), None),
        (None, True, None),
    ):
        with pytest.raises(InputError):
            criterion_limit(sigma, delta, basis)
    with pytest.raises(InputError):
        performance_score("D", 0, 0, criterion_basis="delta_e")
    # 两个依据给出不同结果时，只使用预选依据。
    assert not performance_score(
        "D", 0, 0, sigma=1, delta_e=1, criterion_basis="sigma_pt", u_assigned=0.2
    ).warnings
    assert performance_score(
        "D", 0, 0, sigma=1, delta_e=1, criterion_basis="delta_e", u_assigned=0.2
    ).warnings


def test_template_workflow_and_report(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"], book["项目信息"]["B3"] = "合成", "mg"
    ws = book["方法配置"]
    ws["B3"], ws["B21"], ws["B28"], ws["B29"] = 2.0, "gbt28043", 1.0, "delta_e"
    assert any("B29" in str(d.sqref) for d in ws.data_validations.dataValidation)
    book.save(path)
    data = read_workbook(path)
    data["homogeneity"] = [[0.0, 0.0]] * 10
    data["stability"] = {"基线": [[0.0, 0.0]] * 2, "稳定期": [[0.1, 0.1]] * 2}
    data["participants"] = [{"id": "合成1", "value": 1.0}]
    data["config"]["score_type"] = "D"
    data["assigned_config"] = {
        "method": "known",
        "value": 1.0,
        "uncertainty": 0.1,
        "source": "合成",
        "uncertainty_source": "合成预算",
    }
    result = calculate(data)
    assert result["主判据"]["criterion_basis"] == "delta_e"
    assert result["GB/T均匀性"]["basic_pass"] and result["GB/T稳定性"]["稳定期"]["basic_pass"]
    assert result["GB/T均匀性"]["extended_pass"] is None
    assert "0.1δ_E" in result["参加者统计量"]["合成1"]["D"]["warnings"][0]
    target = tmp_path / "report.docx"
    make_report(target, data, result)
    text = "\n".join(p.text for p in Document(target).paragraphs)
    assert "基本判据依据：delta_e" in text and "基本限值=0.1δ_E" in text
    data["config"]["gbt_hom_rule"] = "extended"
    assert calculate(data)["主判据"]["homogeneity_conclusion"] is None
    data["config"]["gbt_criterion_basis"] = ""
    with pytest.raises(InputError, match="须选择"):
        calculate(data)
    data["config"]["gbt_criterion_basis"] = "sigma_pt"
    assert calculate(data)["GB/T均匀性"]["basic_limit"] == pytest.approx(0.6)
    # GL003 参考限值通过、GB/T 的 δ_E 主限值失败时，不得引用参考结论。
    data["config"].update(gbt_criterion_basis="delta_e", gbt_hom_rule="basic")
    v = 0.2 * math.sqrt(9 / 10)
    data["homogeneity"] = [[-v, -v]] * 5 + [[v, v]] * 5
    data["claims"] = [{"name": "Ss", "value": 0.2, "digits": 2, "source": "合成"}]
    computed = calculate(data)
    assert computed["均匀性"]["Ss_pass"] is True
    assert computed["GB/T均匀性"]["conclusion"] is False
    row = next(r for r in review(data, computed) if r["统计量"] == "Ss")
    assert "CRITERION_EXCEEDED" in row["差异类型"] and "GB/T 预选主判据" in row["说明"]


@pytest.mark.r
@pytest.mark.parametrize("factor", [0.999, 1.0, 1.001])
def test_delta_e_independent_r(tmp_path: Path, factor: float) -> None:
    rscript = shutil.which("Rscript")
    if not rscript:
        pytest.skip("Rscript 不可用")
    v = 0.1 * factor * math.sqrt(9 / 10)
    x, y = [[-v, -v]] * 5 + [[v, v]] * 5, [[0.1 * factor] * 2] * 2
    paths = [tmp_path / "x.csv", tmp_path / "y.csv"]
    for path, rows in zip(paths, (x, y), strict=True):
        path.write_text("\n".join(",".join(map(str, row)) for row in rows) + "\n", encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "validation/r/gbt28043.R"
    output = subprocess.check_output(
        [
            rscript,
            str(script),
            *(str(p) for p in paths),
            "1",
            "0",
            "0",
            "1",
            "delta_e",
            str(0.1 * factor),
        ],
        text=True,
    )
    values = {row["statistic"]: float(row["value"]) for row in csv.DictReader(output.splitlines())}
    h = homogeneity(x, 1, delta_e=1, basis="delta_e")
    s = stability(x, y, 1, delta_e=1, basis="delta_e")
    assert values["ss"] == pytest.approx(h["ss"])
    assert values["difference"] == pytest.approx(s["difference"])
    assert values["basic_limit"] == pytest.approx(h["basic_limit"])
    assert values["uncertainty_warning"] == (factor >= 1)
    # 非边界样本可直接比较不同语言的浮点布尔值；等号另用 compare 测试。
    if factor != 1:
        assert bool(values["hom_basic"]) is h["basic_pass"]
        assert bool(values["stability_basic"]) is s["basic_pass"]
