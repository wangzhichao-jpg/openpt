# SPDX-License-Identifier: Apache-2.0
"""公开合成工作簿和追溯示例的阶段性 R 数值对照。"""

import csv
import json
import math
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path

from openpt.cli import calculate
from openpt.core.homogeneity import analyze
from openpt.core.stability import summary_t
from openpt.io.excel import read_workbook

HERE = Path(__file__).resolve().parent


def main() -> int:
    rscript = shutil.which("Rscript")
    if not rscript:
        raise SystemExit("找不到 Rscript")
    files = sorted((HERE.parent / "examples").glob("*.xlsx"))
    files.append(HERE.parent / "examples/trace_run/input/source.xlsx")
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        source = Path(temp) / "data.csv"

        def call(
            script: str, headers: list[str], records: list[list[object]]
        ) -> list[dict[str, str]]:
            with source.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(headers)
                writer.writerows(records)
            result = subprocess.run(
                [rscript, str(HERE / "r" / script), str(source)],
                check=True,
                capture_output=True,
                text=True,
            )
            return list(csv.DictReader(result.stdout.splitlines()))

        def add(case: str, group: str, key: str, value: float, rvalue: float) -> None:
            error = abs(value - rvalue) / max(abs(value), abs(rvalue)) if value or rvalue else 0.0
            rows.append(
                {
                    "case": case,
                    "group": group,
                    "statistic": key,
                    "openpt": value,
                    "r": rvalue,
                    "relative_error": error,
                    "pass": math.isfinite(error) and error <= 1e-9,
                }
            )

        for file in files:
            case = file.relative_to(HERE.parent / "examples").as_posix()
            data = read_workbook(file)
            result = calculate(data, review_mode=True)
            hom = data["homogeneity"]
            if hom:
                inp = [[i, v] for i, g in enumerate(hom) for v in g]
                own = analyze(hom).to_dict()
                for record in call("anova.R", ["group", "value"], inp):
                    key = record["statistic"]
                    add(case, "均匀性", key, own[key], float(record["value"]))
            baseline = data["stability"].get("基线")
            if baseline:
                for label, samples in data["stability"].items():
                    if label == "基线":
                        continue
                    x = [statistics.mean(unit) for unit in baseline]
                    y = [statistics.mean(unit) for unit in samples]
                    inp = [[1, v] for v in x] + [[2, v] for v in y]
                    own = {}
                    for tag, welch in (("pooled", False), ("welch", True)):
                        t = summary_t(
                            statistics.mean(x),
                            statistics.mean(y),
                            statistics.stdev(x),
                            statistics.stdev(y),
                            len(x),
                            len(y),
                            welch=welch,
                        ).to_dict()
                        own.update({f"{key}_{tag}": t[key] for key in ("t", "df", "p")})
                    for record in call("ttest.R", ["group", "value"], inp):
                        key = record["statistic"]
                        add(case, label + "/单元均值", key, own[key], float(record["value"]))
            participants = data["participants"]
            if not participants:
                continue
            assigned = result.get("指定值与不确定度")
            if assigned and assigned["status"] == "OK":
                inp = [
                    [
                        p["id"],
                        p["value"],
                        assigned["value"],
                        assigned["sigma_prime"],
                        p["u"],
                        assigned["u"],
                        p["U"],
                        assigned["U_assigned"],
                    ]
                    for p in participants
                ]
                own_scores = result["参加者统计量"]
                for record in call(
                    "scores.R", ["id", "x", "X", "sigma", "ux", "uX", "Ux", "UX"], inp
                ):
                    key, ident = record["statistic"], record["id"]
                    add(case, ident, key, own_scores[ident][key]["value"], float(record["value"]))
            elif "参加者z" in result:
                cfg = data["config"]
                inp = [
                    [p["id"], p["value"], cfg["assigned"], cfg["sigma_pt"], 1, 1, 2, 2]
                    for p in participants
                ]
                for record in call(
                    "scores.R", ["id", "x", "X", "sigma", "ux", "uX", "Ux", "UX"], inp
                ):
                    if record["statistic"] == "z":
                        ident = record["id"]
                        add(case, ident, "z", result["参加者z"][ident]["z"], float(record["value"]))
    (HERE / "examples_report.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# 公开工作簿及追溯示例 R 对照",
        "",
        "均匀性和稳定性采用单元均值的对应数值模型，参加者评分基于 openpt 已处理的"
        "指定值、不确定度及 σ 输入，R 独立计算统计量；不代表指定值预算本身已独立验证。"
        "参加者稳健量另见 b1_report。",
        "",
        "| 数据集 | 组/参加者 | 统计量 | openpt | R | 相对误差 | 结论 |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['case']} | {row['group']} | {row['statistic']} | {row['openpt']:.17g} "
            f"| {row['r']:.17g} | {row['relative_error']:.3g} "
            f"| {'通过' if row['pass'] else '差异'} |"
        )
    (HERE / "examples_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return int(any(not row["pass"] for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
