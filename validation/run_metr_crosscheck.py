# SPDX-License-Identifier: Apache-2.0
"""可选 metRology 对照：停止规则不同，只记录差异而非宣称通过。"""

import csv
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from run_r_statistics import python_values

HERE = Path(__file__).resolve().parent


def main() -> int:
    rscript = shutil.which("Rscript")
    if not rscript:
        raise SystemExit("找不到 Rscript")
    cases = json.loads((HERE / "r/anova_cases.json").read_text(encoding="utf-8"))
    rows = []
    version = ""
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "data.csv"
        for name in ("A1", "A2", "负方差"):
            groups = cases[name]
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["group", "value"])
                for i, group in enumerate(groups):
                    writer.writerows((i, v) for v in group)
            completed = subprocess.run(
                [rscript, str(HERE / "r/metrology.R"), str(path)],
                check=True,
                capture_output=True,
                text=True,
            )
            version = completed.stderr.strip()
            own = python_values(groups)
            for record in csv.DictReader(completed.stdout.splitlines()):
                key = record["statistic"]
                rvalue, value = float(record["value"]), own[key]
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
                        "status": "停止规则不同，未判定",
                    }
                )
    (HERE / "metrology_report.json").write_text(
        json.dumps({"package": version, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# metRology 可选对照（停止规则不同，未判定）",
        "",
        f"包及许可证：{version}。包默认数值容差 `.Machine$double.eps^0.25`，最大迭代 25；"
        "openpt 使用 GL002 第三位有效数字停止规则。算法 S 因子也可能因表格修约与包内计算不同。"
        "以下不作通过判定。",
        "",
        "| 数据集 | 量 | openpt | metRology | 相对误差 |",
        "|---|---|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['case']} | {row['statistic']} | {row['openpt']:.17g} | {row['r']:.17g} "
            f"| {row['relative_error']:.3g} |"
        )
    (HERE / "metrology_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
