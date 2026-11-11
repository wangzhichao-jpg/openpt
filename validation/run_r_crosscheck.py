# SPDX-License-Identifier: Apache-2.0
"""阶段性 R ANOVA 对照；本脚本尚未覆盖施工单要求的完整范围。"""

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
import run_r_statistics

from openpt.core.homogeneity import analyze

HERE = Path(__file__).resolve().parent


def main() -> int:
    """输出已有 ANOVA 对照，不将未覆盖部分视为通过。"""
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
    random_run = subprocess.run(
        [sys.executable, str(HERE / "run_r_random.py")],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": "0"},
    )
    if random_run.returncode not in (0, 1) or random_run.stderr:
        raise RuntimeError("随机对照执行错误：" + random_run.stderr)
    random_status = random_run.returncode
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
    random_report = json.loads((HERE / "random_anova_report.json").read_text(encoding="utf-8"))
    (HERE / "crosscheck_report.json").write_text(
        json.dumps(
            {
                "scope": "阶段性 R 对照；未完成施工单",
                "rows": rows,
                "statistics": statistics_rows,
                "b1_and_examples": b1_rows,
                "random_anova": random_report,
                "metRology": metrology,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    lines = [
        "# R 独立对照（阶段性，未完成）",
        "",
        "ANOVA 仅包含 GL003 A.1/A.2、负方差和不平衡合成例；其他统计量见下节。",
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
    random_text = (HERE / "random_anova_report.md").read_text(encoding="utf-8")
    (HERE / "crosscheck_report.md").write_text(
        "\n".join(lines)
        + "\n\n"
        + statistics_report
        + "\n"
        + b1_text
        + "\n"
        + random_text
        + "\n"
        + metrology_text,
        encoding="utf-8",
    )
    return (
        0
        if all(row["pass"] for row in rows) and statistics_status == b1_status == random_status == 0
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
