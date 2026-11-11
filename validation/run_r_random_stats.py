# SPDX-License-Identifier: Apache-2.0
"""将 200 组固定 CSV 用于 t、算法 A/S、中位数及评分的 R 数值对照。"""

import csv
import json
import math
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

from run_r_statistics import python_values

HERE = Path(__file__).resolve().parent


def main() -> int:
    rscript = shutil.which("Rscript")
    if not rscript:
        raise SystemExit("找不到 Rscript")
    cases: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    with (HERE / "random_anova_input.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            cases[row["case"]][int(row["group"])].append(float(row["value"]))
    if len(cases) != 200:
        raise RuntimeError("随机 CSV 不是 200 组")
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "data.csv"
        for name, mapping in sorted(cases.items()):
            groups = [mapping[i] for i in sorted(mapping)]
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["group", "value"])
                for i, group in enumerate(groups):
                    writer.writerows((i, value) for value in group)
            process = subprocess.run(
                [rscript, str(HERE / "r/statistics.R"), str(path)],
                check=True,
                capture_output=True,
                text=True,
            )
            rvalues = {
                row["statistic"]: float(row["value"])
                for row in csv.DictReader(process.stdout.splitlines())
            }
            own = python_values(groups)
            for key, rvalue in rvalues.items():
                if key not in own:
                    rows.append(
                        {
                            "case": name,
                            "statistic": key,
                            "openpt": None,
                            "r": rvalue,
                            "relative_error": None,
                            "status": "仅报告",
                        }
                    )
                    continue
                value = own[key]
                error = (
                    abs(value - rvalue) / max(abs(value), abs(rvalue)) if value or rvalue else 0.0
                )
                if key in ("A_x", "A_s", "S_w"):
                    scale = abs(own["S_w"] if key == "S_w" else own["A_s"])
                    unit = 10 ** (math.floor(math.log10(scale)) - 2) if scale else 0
                    ok = abs(value - rvalue) <= unit
                else:
                    ok = error <= 1e-9
                rows.append(
                    {
                        "case": name,
                        "statistic": key,
                        "openpt": value,
                        "r": rvalue,
                        "relative_error": error,
                        "status": "通过" if ok else "差异",
                    }
                )
    (HERE / "random_statistics_report.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# 200 组随机数据的 t、稳健统计和评分对照",
        "",
        "输入为 random_anova_input.csv；每组的前两组值用作 t 检验数值测试，"
        "所有值用于算法 A 和分位数。算法 S 用各组标准差作为合成输入、统一自由度 1，"
        "仅验证数值公式，并不声称各组实际自由度为 1。算法 A/S 均采用 GL002 停止规则，"
        "迭代次数须相同；值采用显示位一末位容差。type 6 仅报告。",
        "",
        "| 数据集 | 统计量 | openpt | R | 相对误差 | 结论 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in rows:
        value = "—" if row["openpt"] is None else f"{row['openpt']:.17g}"
        error = "—" if row["relative_error"] is None else f"{row['relative_error']:.3g}"
        lines.append(
            f"| {row['case']} | {row['statistic']} | {value} | {row['r']:.17g} "
            f"| {error} | {row['status']} |"
        )
    (HERE / "random_statistics_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return int(any(row["status"] == "差异" for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
