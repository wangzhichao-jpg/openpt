# SPDX-License-Identifier: Apache-2.0
"""R 独立统计脚本的可选冒烟对照。"""

import csv
import shutil
import subprocess
from decimal import ROUND_DOWN, localcontext
from pathlib import Path

import pytest

from openpt.cli import calculate
from openpt.core.robust import algorithm_a, algorithm_s
from openpt.review.compare import review


@pytest.mark.r
def test_r_robust_statistics(tmp_path: Path) -> None:
    rscript = shutil.which("Rscript")
    if not rscript:
        pytest.skip("Rscript 不可用")
    source = tmp_path / "data.csv"
    source.write_text("group,value\n1,1\n1,3\n2,2\n2,4\n", encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "validation/r/statistics.R"
    process = subprocess.run(
        [rscript, str(script), str(source)], check=True, capture_output=True, text=True
    )
    result = {
        row["statistic"]: float(row["value"]) for row in csv.DictReader(process.stdout.splitlines())
    }
    a = algorithm_a([1, 3, 2, 4])
    s = algorithm_s([2**0.5, 2**0.5], 1)
    assert result["A_x"] == pytest.approx(a.x, rel=1e-9)
    assert result["A_s"] == pytest.approx(a.s, rel=1e-9)
    assert result["A_iterations"] == a.iterations
    assert result["S_w"] == pytest.approx(s.w, rel=1e-9)
    assert result["S_iterations"] == s.iterations
    assert result["z"] == pytest.approx(-1 / 1.2)


def test_gbt_algorithm_a_stopping_differs_from_gl002() -> None:
    data = [-5, -4, -3, -2, -1, 0, 1, 2, 3, 40]
    gl = algorithm_a(data, rule="gl002")
    standard = algorithm_a(data, rule="gbt28043")
    assert gl.converged and standard.converged
    assert gl.iterations == 2 and standard.iterations == 3
    assert gl.x != standard.x
    with localcontext() as context:
        context.rounding = ROUND_DOWN
        altered_context = algorithm_a(data, rule="gbt28043")
    assert altered_context.x == standard.x and altered_context.iterations == standard.iterations

    workflow = {
        "config": {"algorithm_a_rule": "gl002"},
        "participants": [{"id": str(i), "value": x} for i, x in enumerate(data)],
        "homogeneity": [],
        "stability": {},
        "claims": [
            {"name": "x*", "value": standard.x, "digits": 8, "source": "合成", "model": "gbt28043"}
        ],
    }
    rows = review(workflow, calculate(workflow))
    assert rows[0]["显示一致"] is True and rows[0]["推荐一致"] is False
    assert "STOP_RULE_SENSITIVITY" in rows[0]["差异类型"]


@pytest.mark.r
def test_r_gbt_algorithm_a(tmp_path: Path) -> None:
    rscript = shutil.which("Rscript")
    if not rscript:
        pytest.skip("Rscript 不可用")
    data = [-5, -4, -3, -2, -1, 0, 1, 2, 3, 40]
    source = tmp_path / "data.csv"
    source.write_text("value\n" + "\n".join(map(str, data)) + "\n", encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "validation/r/robust_a_gbt.R"
    process = subprocess.run(
        [rscript, str(script), str(source)], check=True, capture_output=True, text=True
    )
    result = {
        row["statistic"]: float(row["value"]) for row in csv.DictReader(process.stdout.splitlines())
    }
    actual = algorithm_a(data, rule="gbt28043")
    assert result["A_x"] == pytest.approx(actual.x, rel=1e-12, abs=1e-14)
    assert result["A_s"] == pytest.approx(actual.s, rel=1e-12, abs=1e-14)
    assert result["A_iterations"] == actual.iterations
