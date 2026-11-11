# SPDX-License-Identifier: Apache-2.0
"""对照全部观测值相同的退化输入，不把 R 的近零舍入残差当成真实信息。"""

import csv
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from openpt.core.homogeneity import analyze

HERE = Path(__file__).resolve().parent


def main() -> int:
    rscript = shutil.which("Rscript")
    if not rscript:
        raise SystemExit("找不到 Rscript")
    groups = [[10.0, 10.0] for _ in range(10)]
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "data.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["group", "value"])
            for i, group in enumerate(groups):
                writer.writerows((i, value) for value in group)
        process = subprocess.run(
            [rscript, str(HERE / "r/anova.R"), str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
        rvalues = {
            row["statistic"]: float(row["value"])
            for row in csv.DictReader(process.stdout.splitlines())
        }
    own = analyze(groups).to_dict()
    report = {
        "case": "全部相同",
        "openpt_status": own["status"],
        "openpt_F": own["F"],
        "openpt_p": own["p"],
        "r_values": rvalues,
        "r_warning": process.stderr.strip(),
        "status": "差异：R 近零舍入残差产生 F，openpt 标记不可判定",
    }
    (HERE / "degenerate_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# 全部相同数据的退化 ANOVA",
        "",
        "10 个样品每个两次均为 10。理论组间及组内均方均为零，F 为 0/0；"
        "openpt 将其标记不可判定。R `aov` 线性模型可能因舍入给出非零极小均方和有限 F，"
        "其自身同时警告近乎完美拟合时 F 检验不可靠。该差异须保留，不能用 R 的数值当作可判定结果。",
        "",
        f"- openpt：状态 `{own['status']}`，F={own['F']}，p={own['p']}。",
        f"- R：MS_between={rvalues['MS_between']:.17g}，MS_within={rvalues['MS_within']:.17g}，"
        f"F={rvalues['F']:.17g}，p={rvalues['p']:.17g}。",
        f"- R 原始警告：`{process.stderr.strip()}`。",
    ]
    (HERE / "degenerate_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
