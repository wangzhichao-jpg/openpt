# SPDX-License-Identifier: Apache-2.0
"""汇总 R 独立对照；对差异和无法直接比较的边界如实报告。"""

import csv
import hashlib
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


def known_difference(row: dict, known: list[dict]) -> str | None:
    """仅接受明确列出的数据集、统计量及严格数值条件。"""
    for entry in known:
        if entry.get("case") != row.get("case") or entry.get("statistic") != row.get("statistic"):
            continue
        if entry.get("input_sha256") is not None and entry["input_sha256"] != row.get(
            "input_sha256"
        ):
            continue
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            continue
        condition = entry.get("condition")
        if condition == "openpt_zero_r_abs_lt_1e-12":
            value, rvalue = row.get("openpt"), row.get("r")
            if (
                value == 0
                and isinstance(rvalue, (int, float))
                and math.isfinite(rvalue)
                and abs(rvalue) < 1e-12
            ):
                return reason
        elif condition == "indeterminate_zero_variance_r_residual_lt_1e-12":
            rvalues = row.get("r_values", {})
            if (
                row.get("openpt_status") == "INDETERMINATE"
                and row.get("openpt_F") is None
                and row.get("openpt_p") is None
                and all(
                    isinstance(rvalues.get(key), (int, float))
                    and math.isfinite(rvalues[key])
                    and abs(rvalues[key]) < 1e-12
                    for key in ("MS_between", "MS_within")
                )
                and all(
                    isinstance(rvalues.get(key), (int, float)) and math.isfinite(rvalues[key])
                    for key in ("F", "p")
                )
                and 0 <= rvalues["p"] <= 1
            ):
                return reason
    return None


def main() -> int:
    """汇总独立对照，已知差异明确列出，其他差异导致失败。"""
    rscript = shutil.which("Rscript")
    if not rscript:
        raise SystemExit("找不到 Rscript；没有执行对照")
    cases = json.loads((HERE / "r/anova_cases.json").read_text(encoding="utf-8"))
    known = json.loads((HERE / "known_differences.json").read_text(encoding="utf-8"))
    if not isinstance(known, list):
        raise ValueError("已知差异清单必须为数组")
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
    for row in rows:
        row["known_reason"] = None if row["pass"] else known_difference(row, known)
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
    degenerate["known_reason"] = known_difference({**degenerate, "statistic": "F,p"}, known)
    random_stats_rows = json.loads(
        (HERE / "random_statistics_report.json").read_text(encoding="utf-8")
    )
    random_report = json.loads((HERE / "random_anova_report.json").read_text(encoding="utf-8"))
    random_inputs: dict[str, list[list[int]]] = {}
    with (HERE / "random_anova_input.csv").open(encoding="utf-8", newline="") as stream:
        for item in csv.DictReader(stream):
            random_inputs.setdefault(item["case"], []).append(
                [int(item["group"]), int(item["value"])]
            )
    for row in random_report["rows"]:
        if not row["pass"]:
            encoded = json.dumps(random_inputs[row["case"]], separators=(",", ":")).encode()
            row["input_sha256"] = hashlib.sha256(encoded).hexdigest()
            row["known_reason"] = known_difference(row, known)
    random_accepted = random_status == 0 or (
        random_status == 1
        and all(row["pass"] or row.get("known_reason") for row in random_report["rows"])
    )
    (HERE / "crosscheck_report.json").write_text(
        json.dumps(
            {
                "scope": "R 独立对照；已知差异及未覆盖接口保留",
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
        "严格相对误差仍如实记录；只有已知差异清单中满足具体条件的差异可通过门槛。",
        "",
        "| 数据集 | 统计量 | openpt | R | 相对误差 | 结论 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in rows:
        conclusion = "通过" if row["pass"] else "差异"
        if row["known_reason"]:
            conclusion = "已知差异：" + row["known_reason"]
        lines.append(
            f"| {row['case']} | {row['statistic']} | {row['openpt']:.17g} | {row['r']:.17g} "
            f"| {row['relative_error']:.3g} | {conclusion} |"
        )
    statistics_report = (HERE / "statistics_report.md").read_text(encoding="utf-8")
    b1_text = (HERE / "b1_report.md").read_text(encoding="utf-8")
    examples_text = (HERE / "examples_report.md").read_text(encoding="utf-8")
    degenerate_text = (HERE / "degenerate_report.md").read_text(encoding="utf-8")
    random_text = (HERE / "random_anova_report.md").read_text(encoding="utf-8")
    known_random = sum(bool(row.get("known_reason")) for row in random_report["rows"])
    random_text += f"\n其中 {known_random} 条差异与清单中的输入哈希和数值条件一致。\n"
    if degenerate["known_reason"]:
        degenerate_text += "\n清单已知差异：" + degenerate["known_reason"] + "\n"
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
        if all(row["pass"] or row["known_reason"] for row in rows)
        and (degenerate_status == 0 or (degenerate_status == 1 and degenerate["known_reason"]))
        and random_accepted
        and statistics_status == b1_status == examples_status == random_stats_status == 0
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
