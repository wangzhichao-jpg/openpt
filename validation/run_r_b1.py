# SPDX-License-Identifier: Apache-2.0
"""GL002 表 B1 与公开示例中的参加者数据的 R 稳健对照。"""

import csv
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from openpt.core.robust import algorithm_a, median_niqr
from openpt.io.excel import read_workbook

HERE = Path(__file__).resolve().parent


def main() -> int:
    rscript = shutil.which("Rscript")
    if not rscript:
        raise SystemExit("找不到 Rscript")
    cases = json.loads((HERE / "r/b1_cases.json").read_text(encoding="utf-8"))
    example_dir = HERE.parent / "examples"
    for file in sorted(example_dir.glob("*.xlsx")):
        participants = read_workbook(file)["participants"]
        if participants:
            cases[f"示例/{file.name}"] = [p["value"] for p in participants]
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        source = Path(temp) / "input.csv"
        for name, values in cases.items():
            with source.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["value"])
                writer.writerows([value] for value in values)
            result = subprocess.run(
                [rscript, str(HERE / "r/robust_a.R"), str(source)],
                check=True,
                capture_output=True,
                text=True,
            )
            rvalues = {
                row["statistic"]: float(row["value"])
                for row in csv.DictReader(result.stdout.splitlines())
            }
            a = algorithm_a(values).to_dict()
            q = median_niqr(values).to_dict()
            own = {
                "A_x": a["x"],
                "A_s": a["s"],
                "A_iterations": a["iterations"],
                "median": q["median"],
                "niqr": q["niqr"],
            }
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
                if key in ("A_x", "A_s"):
                    scale = abs(own["A_s"])
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
    (HERE / "b1_report.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# GL002 表 B1 与公开示例参加者稳健对照",
        "",
        "B1 的 S、D 由 A/B 原值生成。算法 A 使用相同 GL002 停止规则并核对迭代次数，"
        "估计值以相应显示位一末位为容差；type 6 仅供参考。"
        "这里只比较参加者稳健量，不意味着示例的所有统计量均已对照。",
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
    (HERE / "b1_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return int(any(row["status"] == "差异" for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
