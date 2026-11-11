# SPDX-License-Identifier: Apache-2.0
"""三路线阶段性同输入比较；pt13528 为可选依赖，不是运行依赖。"""

import json
import statistics
from pathlib import Path

from pt13528.homogeneity import homogeneity, stability_t_test
from pt13528.robust import algorithm_a, algorithm_s, median, niqr
from pt13528.scores import en_score, z_prime_score, z_score, zeta_score

HERE = Path(__file__).resolve().parent


def main() -> int:
    cases = json.loads((HERE / "r/anova_cases.json").read_text(encoding="utf-8"))
    anova = json.loads((HERE / "crosscheck_report.json").read_text(encoding="utf-8"))["rows"]
    stats = json.loads((HERE / "statistics_report.json").read_text(encoding="utf-8"))
    rows = []
    for name in ("A1", "A2", "负方差"):
        groups = cases[name]
        x, y = groups[:2]
        flat = [v for group in groups for v in group]
        h = homogeneity(groups)
        a = algorithm_a(flat, tol="equivalent-figure")
        s = algorithm_s([statistics.stdev(group) for group in groups], 1, tol="equivalent-figure")
        pooled = stability_t_test(x, y, equal_var=True)
        welch = stability_t_test(x, y, equal_var=False)
        x1, x2 = statistics.mean(x), statistics.mean(y)
        pt = {
            "F": h.f_statistic,
            "Ss": h.s_s,
            "A_x": a["location"],
            "A_s": a["scale"],
            "A_iterations": a["iterations"],
            "S_w": s["scale"],
            "S_iterations": s["iterations"],
            "median": median(flat),
            "niqr": niqr(flat),
            "z": z_score(x1, x2, 1.2),
            "zprime": z_prime_score(x1, x2, 1.2, 0.2),
            "zeta": zeta_score(x1, x2, 0.4, 0.2),
            "En": en_score(x1, x2, 0.8, 0.4),
        }
        for tag, result in (("pooled", pooled), ("welch", welch)):
            for index, key in enumerate(("t", "df", "p")):
                pt[f"{key}_{tag}"] = result[index]
        for source in (anova, stats):
            for record in source:
                if record["case"] != name or record["statistic"] not in pt:
                    continue
                key = record["statistic"]
                own, pt_value, r_value = record["openpt"], pt[key], record["r"]
                rel_pt = (
                    abs(own - pt_value) / max(abs(own), abs(pt_value)) if own or pt_value else 0
                )
                rel_r = abs(own - r_value) / max(abs(own), abs(r_value)) if own or r_value else 0
                rows.append(
                    {
                        "case": name,
                        "statistic": key,
                        "openpt": own,
                        "pt13528": pt_value,
                        "r": r_value,
                        "relative_pt": rel_pt,
                        "relative_r": rel_r,
                        "pass": rel_pt <= 1e-9 and rel_r <= 1e-9,
                    }
                )
    (HERE / "threeway_report.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# 三路线同输入阶段性比较",
        "",
        "pt13528 0.1.11（LGPL-3.0-or-later）与 openpt 共用 SciPy，R 为独立运行。"
        "均采用相同数据；算法 A/S 为 GL002 对应位停止规则及 pt13528 的 equivalent-figure 规则，"
        "同时比较迭代次数。双样本 t 输入只是合成数值样本，不证明独立性。"
        "此表未覆盖所有施工单样本及统计量，剩余范围仍待验证。",
        "",
        "|数据集|统计量|openpt|pt13528|R|pt 相对误差|R 相对误差|结论|",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"|{row['case']}|{row['statistic']}|{row['openpt']:.17g}|{row['pt13528']:.17g}|"
            f"{row['r']:.17g}|{row['relative_pt']:.3g}|{row['relative_r']:.3g}|"
            f"{'通过' if row['pass'] else '差异'}|"
        )
    (HERE / "threeway_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return int(any(not row["pass"] for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
