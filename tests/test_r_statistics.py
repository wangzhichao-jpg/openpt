# SPDX-License-Identifier: Apache-2.0
"""R 独立统计脚本的可选冒烟对照。"""

import csv
import shutil
import subprocess
from pathlib import Path

import pytest

from openpt.core.robust import algorithm_a, algorithm_s


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
