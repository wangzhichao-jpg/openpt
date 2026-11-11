# SPDX-License-Identifier: Apache-2.0
"""汇总 R 独立对照；对差异和无法直接比较的边界如实报告。"""

import csv
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import run_metr_crosscheck
import run_r_b1
import run_r_degenerate
import run_r_examples
import run_r_random_stats
import run_r_statistics

from openpt.core.homogeneity import analyze

HERE = Path(__file__).resolve().parent


def main() -> int:
    """汇总数值对照，不将未覆盖部分或理论零值差异视为通过。"""
    rscript = shutil.which("Rscript")
    if not rscript:
        raise SystemExit("找不到 Rscript；没有执行对照")
    cases = json.loads((HERE / "r/anova_cases.json").read_text(encoding="utf-8"))
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "input.csv"
        for name, groups in cases.items():
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["group", "value"])
                for index, group in enumerate(groups):
                    writer.writerows((index, value) for value in group)
            result = subprocess.run(
                [rscript, str(HERE / "r/anova.R"), str(path)],
                check=True,
                capture_output=True,
                text=True,
            )
            rvalues = {
                row["statistic"]: float(row["value"])
                for row in csv.DictReader(result.stdout.splitlines())
            }
            own = analyze(groups).to_dict()
            for key, rvalue in rvalues.items():
                value = own[key]
                error = (
                    abs(value - rvalue) / max(abs(value), abs(rvalue)) if value or rvalue else 0.0
                )
                rows.append(
                    {
                        "case": name,
                        "statistic": key,
                        "openpt": value,
                        "r": rvalue,
                        "relative_error": error,
                        "pass": math.isfinite(error) and error <= 1e-9,
                    }
                )
    statistics_status = run_r_statistics.main()
    b1_status = run_r_b1.main()
    examples_status = run_r_examples.main()
    degenerate_status = run_r_degenerate.main()
    random_run = subprocess.run(
        [sys.executable, str(HERE / "run_r_random.py")],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": "0"},
    )
    if random_run.returncode not in (0, 1) or random_run.stderr:
        raise RuntimeError("随机对照执行错误：" + random_run.stderr)
    random_status = random_run.returncode
    random_stats_status = run_r_random_stats.main()
    package_check = subprocess.run(
        [rscript, "-e", 'quit(status=if (requireNamespace("metRology", quietly=TRUE)) 0 else 1)'],
        capture_output=True,
        text=True,
    )
    metrology = None
    metrology_text = "\nmetRology 不可用；未执行该包对照。\n"
    if package_check.returncode == 0:
        run_metr_crosscheck.main()
        metrology = json.loads((HERE / "metrology_report.json").read_text(encoding="utf-8"))
        metrology_text = (HERE / "metrology_report.md").read_text(encoding="utf-8")
    statistics_rows = json.loads((HERE / "statistics_report.json").read_text(encoding="utf-8"))
    b1_rows = json.loads((HERE / "b1_report.json").read_text(encoding="utf-8"))
    examples_rows = json.loads((HERE / "examples_report.json").read_text(encoding="utf-8"))
    degenerate = json.loads((HERE / "degenerate_report.json").read_text(encoding="utf-8"))
    random_stats_rows = json.loads(
        (HERE / "random_statistics_report.json").read_text(encoding="utf-8")
    )
    random_report = json.loads((HERE / "random_anova_report.json").read_text(encoding="utf-8"))
    (HERE / "crosscheck_report.json").write_text(
        json.dumps(
            {
                "scope": "R 独立对照；理论零值差异及未覆盖接口保留",
                "rows": rows,
                "statistics": statistics_rows,
                "b1_and_examples": b1_rows,
                "examples": examples_rows,
                "degenerate": degenerate,
                "random_anova": random_report,
                "random_statistics": random_stats_rows,
                "metRology": metrology,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    lines = [
        "# R 独立对照报告",
        "",
        "固定 ANOVA 含 GL003 A.1/A.2、负方差和不平衡合成例；其他公开、随机与退化输入见下节。",
        "",
        "负方差例组间均方理论上为零；R 线性模型运算产生约 1e-31 的舍入残差，"
        "严格相对误差因与零比较为 1，按施工单如实记为差异，不采用绝对容差掩盖。",
        "",
        "| 数据集 | 统计量 | openpt | R | 相对误差 | 结论 |",
        "|---|---|---:|---:|---:|---|",
    ]
    lines.extend(
        f"| {r['case']} | {r['statistic']} | {r['openpt']:.17g} | {r['r']:.17g} "
        f"| {r['relative_error']:.3g} | {'通过' if r['pass'] else '差异'} |"
        for r in rows
    )
    statistics_report = (HERE / "statistics_report.md").read_text(encoding="utf-8")
    b1_text = (HERE / "b1_report.md").read_text(encoding="utf-8")
    examples_text = (HERE / "examples_report.md").read_text(encoding="utf-8")
    degenerate_text = (HERE / "degenerate_report.md").read_text(encoding="utf-8")
    random_text = (HERE / "random_anova_report.md").read_text(encoding="utf-8")
    random_stats_text = (HERE / "random_statistics_report.md").read_text(encoding="utf-8")
    (HERE / "crosscheck_report.md").write_text(
        "\n".join(lines)
        + "\n\n"
        + statistics_report
        + "\n"
        + b1_text
        + "\n"
        + examples_text
        + "\n"
        + degenerate_text
        + "\n"
        + random_text
        + "\n"
        + random_stats_text
        + "\n"
        + metrology_text,
        encoding="utf-8",
    )
    return (
        0
        if all(row["pass"] for row in rows)
        and statistics_status
        == b1_status
        == examples_status
        == degenerate_status
        == random_status
        == random_stats_status
        == 0
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
