# SPDX-License-Identifier: Apache-2.0
"""阶段性 GL002 及 t 检验独立对照；未覆盖施工单全部数据集。"""

import csv
import json
import math
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path

from openpt.core.robust import algorithm_a, algorithm_s, median_niqr
from openpt.core.scores import performance_score
from openpt.core.stability import analyze, summary_t

HERE = Path(__file__).resolve().parent


def python_values(groups: list[list[float]]) -> dict[str, float]:
    """以相同输入调用 openpt；R 部分另按公式独立实现。"""
    x, y = groups[:2]
    one = analyze(None, [[v] for v in x], method="one_sample", reference=0).to_dict()
    pooled = summary_t(
        statistics.mean(x),
        statistics.mean(y),
        statistics.stdev(x),
        statistics.stdev(y),
        len(x),
        len(y),
    ).to_dict()
    welch = summary_t(
        statistics.mean(x),
        statistics.mean(y),
        statistics.stdev(x),
        statistics.stdev(y),
        len(x),
        len(y),
        welch=True,
    ).to_dict()
    flat = [v for group in groups for v in group]
    a = algorithm_a(flat).to_dict()
    s = algorithm_s([statistics.stdev(group) for group in groups], 1).to_dict()
    q = median_niqr(flat).to_dict()
    result = {
        f"{key}_{kind}": record[key]
        for kind, record in (("one", one), ("pooled", pooled), ("welch", welch))
        for key in ("t", "df", "p")
    }
    result.update(
        {
            "A_x": a["x"],
            "A_s": a["s"],
            "A_iterations": a["iterations"],
            "S_w": s["w"],
            "S_iterations": s["iterations"],
            "median": q["median"],
            "niqr": q["niqr"],
        }
    )
    for name in ("z", "zprime", "zeta", "En"):
        result[name] = performance_score(
            name,
            statistics.mean(x),
            statistics.mean(y),
            sigma=1.2,
            u_assigned=0.2,
            u_participant=0.4,
            U_assigned=0.4,
            U_participant=0.8,
            k_assigned=2,
            k_participant=2,
            independent=True,
        ).value
    return result


def main() -> int:
    rscript = shutil.which("Rscript")
    if not rscript:
        raise SystemExit("找不到 Rscript")
    cases = json.loads((HERE / "r/anova_cases.json").read_text(encoding="utf-8"))
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "data.csv"
        for name in ("A1", "A2", "负方差"):
            groups = cases[name]
            with path.open("w", newline="", encoding="utf-8") as stream:
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
    (HERE / "statistics_report.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# 阶段性 R 对照：t、稳健统计和评分",
        "",
        "仅为 A1、A2 和负方差合成数据的数值试验；前两组重复值仅作为计算样本，"
        "不构成实验独立性证明。算法 A、S 均采用 GL002 对应位停止规则，"
        "比较误差为显示位数的一末位；R type 6 仅作参考，不作为通过条件。"
        "未覆盖的施工单数据与条件不能视为通过。",
        "",
        "| 数据集 | 统计量 | openpt | R | 相对误差 | 结论 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in rows:
        left = "—" if row["openpt"] is None else f"{row['openpt']:.17g}"
        error = "—" if row["relative_error"] is None else f"{row['relative_error']:.3g}"
        lines.append(
            f"| {row['case']} | {row['statistic']} | {left} | {row['r']:.17g} "
            f"| {error} | {row['status']} |"
        )
    (HERE / "statistics_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return int(any(row["status"] == "差异" for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
