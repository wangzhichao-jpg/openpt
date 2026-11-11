# SPDX-License-Identifier: Apache-2.0
"""可选 base R 不平衡 ANOVA 对照。"""

import csv
import shutil
import subprocess
from pathlib import Path

import pytest

from openpt.core.homogeneity import analyze


@pytest.mark.r
def test_r_anova(tmp_path: Path) -> None:
    rscript = shutil.which("Rscript")
    if not rscript:
        pytest.skip("Rscript 不可用")
    path = tmp_path / "input.csv"
    path.write_text("group,value\n1,1\n1,3\n2,2\n2,4\n2,6\n", encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "validation/r/anova.R"
    completed = subprocess.run(
        [rscript, str(script), str(path)], check=True, capture_output=True, text=True
    )
    results = {
        row["statistic"]: float(row["value"])
        for row in csv.DictReader(completed.stdout.splitlines())
    }
    own = analyze([[1, 3], [2, 4, 6]]).to_dict()
    for name, number in results.items():
        assert own[name] == pytest.approx(number, rel=1e-9, abs=0)
