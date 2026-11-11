# SPDX-License-Identifier: Apache-2.0
"""固定种子的 200 组 Hypothesis 随机 ANOVA：写 CSV 并交 R 计算。"""

import csv
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import hypothesis
from hypothesis import HealthCheck, given, seed, settings
from hypothesis import strategies as st

from openpt.core.homogeneity import analyze

HERE = Path(__file__).resolve().parent
SEED = 20261112


def generate() -> list[list[list[int]]]:
    """固定种子、禁用数据库；避免组内完全一致的退化设计。"""
    groups: list[list[list[int]]] = []
    group = st.lists(st.integers(-1000, 1000), min_size=2, max_size=5).filter(
        lambda values: len(set(values)) >= 2
    )

    @seed(SEED)
    @settings(
        max_examples=200,
        database=None,
        deadline=None,
        suppress_health_check=[HealthCheck.filter_too_much],
    )
    @given(st.lists(group, min_size=2, max_size=7))
    def collect(value: list[list[int]]) -> None:
        groups.append(value)

    collect()
    if len(groups) != 200:
        raise RuntimeError(f"Hypothesis 产生 {len(groups)} 组而不是 200 组")
    return groups


def main() -> int:
    rscript = shutil.which("Rscript")
    if not rscript:
        raise SystemExit("找不到 Rscript")
    cases = generate()
    data_path = HERE / "random_anova_input.csv"
    with data_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["case", "group", "value"])
        for index, case in enumerate(cases):
            for group_index, group in enumerate(case):
                writer.writerows((f"case_{index:03}", group_index, v) for v in group)
    process = subprocess.run(
        [rscript, str(HERE / "r/random_anova.R"), str(data_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    ours = {f"case_{i:03}": analyze(case).to_dict() for i, case in enumerate(cases)}
    rows = []
    for record in csv.DictReader(process.stdout.splitlines()):
        case, metric = record["case"], record["statistic"]
        rvalue = float(record["value"])
        value = ours[case][metric]
        error = abs(value - rvalue) / max(abs(value), abs(rvalue)) if value or rvalue else 0.0
        rows.append(
            {
                "case": case,
                "statistic": metric,
                "openpt": value,
                "r": rvalue,
                "relative_error": error,
                "pass": math.isfinite(error) and error <= 1e-9,
            }
        )
    if len(rows) != 1200:
        raise RuntimeError(f"对照仅获得 {len(rows)} 行")
    meta = {
        "seed": SEED,
        "python_hash_seed": 0,
        "hypothesis_version": hypothesis.__version__,
        "case_count": len(cases),
        "rows": rows,
    }
    (HERE / "random_anova_report.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# 固定种子随机 ANOVA 对照",
        "",
        f"Hypothesis {hypothesis.__version__}，种子 {SEED}，PYTHONHASHSEED=0；200 组，"
        "输入见 random_anova_input.csv。仅测试 ANOVA，不代表其他统计量或真实试验设计已验证。",
        "",
        "严格相对误差下，若理论为零而 R 线性模型运算出现极小浮点残差，"
        "相对误差为 1，仍列为差异，不用绝对容差掩盖；其他差异须另行分析。",
        "",
        "| 数据集 | 统计量 | openpt | R | 相对误差 | 结论 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['case']} | {row['statistic']} | {row['openpt']:.17g} | {row['r']:.17g} "
            f"| {row['relative_error']:.3g} | {'通过' if row['pass'] else '差异'} |"
        )
    (HERE / "random_anova_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return int(any(not row["pass"] for row in rows))


if __name__ == "__main__":
    # Hypothesis 可能受到 Python 哈希随机化影响；固定后重启本进程。
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.execvpe(
            sys.executable, [sys.executable, *sys.argv], {**os.environ, "PYTHONHASHSEED": "0"}
        )
    raise SystemExit(main())
