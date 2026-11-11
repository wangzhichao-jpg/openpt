# SPDX-License-Identifier: Apache-2.0
"""比较同一批固定随机 CSV 的 openpt、R 和可选 pt13528 路线。"""

import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pt13528.homogeneity import homogeneity, stability_t_test
from pt13528.robust import algorithm_a, algorithm_s, median, niqr
from pt13528.scores import en_score, z_prime_score, z_score, zeta_score

HERE = Path(__file__).resolve().parent


def pt_values(groups: list[list[float]]) -> tuple[dict[str, float], dict[str, str]]:
    """仅调用第三方公开 API；不更改或复制该库代码。"""
    out: dict[str, float] = {}
    missing: dict[str, str] = {}
    x, y = groups[:2]
    values = [v for group in groups for v in group]
    if len({len(group) for group in groups}) == 1:
        try:
            h = homogeneity(groups)
            if h.f_statistic is not None:
                out["F"] = h.f_statistic
            else:
                missing["F"] = "pt13528 返回不可判定"
            out["Ss"] = h.s_s
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            missing.update({"F": str(exc), "Ss": str(exc)})
    else:
        missing.update({"F": "接口不支持不平衡重复数", "Ss": "接口不支持不平衡重复数"})
    for tag, equal in [("pooled", True), ("welch", False)]:
        try:
            result = stability_t_test(x, y, equal_var=equal)
            for i, key in enumerate(("t", "df", "p")):
                if result[i] is not None:
                    out[f"{key}_{tag}"] = abs(result[i]) if key == "t" else result[i]
                    if key == "t":
                        out[f"signed_t_{tag}"] = result[i]
                else:
                    missing[f"{key}_{tag}"] = "pt13528 返回不可判定"
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            missing.update({f"{key}_{tag}": str(exc) for key in ("t", "df", "p")})
    try:
        a = algorithm_a(values, tol="equivalent-figure")
        out.update({"A_x": a["location"], "A_s": a["scale"], "A_iterations": a["iterations"]})
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        missing.update({key: str(exc) for key in ("A_x", "A_s", "A_iterations")})
    try:
        s = algorithm_s([statistics.stdev(group) for group in groups], 1, tol="equivalent-figure")
        out.update({"S_w": s["scale"], "S_iterations": s["iterations"]})
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        missing.update({key: str(exc) for key in ("S_w", "S_iterations")})
    out["median"] = median(values)
    out["niqr"] = niqr(values, quantile_method="linear")
    x1, x2 = statistics.mean(x), statistics.mean(y)
    out.update(
        {
            "z": z_score(x1, x2, 1.2),
            "zprime": z_prime_score(x1, x2, 1.2, 0.2),
            "zeta": zeta_score(x1, x2, 0.4, 0.2),
            "En": en_score(x1, x2, 0.8, 0.4),
        }
    )
    return out, missing


def relative(a: float, b: float) -> float:
    return abs(a - b) / max(abs(a), abs(b)) if a or b else 0.0


def main() -> int:
    groups: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    with (HERE / "random_anova_input.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            groups[row["case"]][int(row["group"])].append(float(row["value"]))
    raw = json.loads((HERE / "random_anova_report.json").read_text(encoding="utf-8"))["rows"]
    raw += json.loads((HERE / "random_statistics_report.json").read_text(encoding="utf-8"))
    outputs: dict[str, tuple[dict[str, float], dict[str, str]]] = {}
    for name, data in groups.items():
        outputs[name] = pt_values([data[k] for k in sorted(data)])
    rows: list[dict[str, Any]] = []
    for source in raw:
        key, name = source["statistic"], source["case"]
        own, r = source["openpt"], source["r"]
        pt, missing = outputs[name]
        reason = missing.get(key, "pt13528 接口未提供该统计量")
        if own is None:
            status, error, value = "R type 6 仅报告", None, None
        elif key not in pt:
            status, error, value = "pt13528 未覆盖", None, None
        else:
            value = pt[key]
            error = relative(own, value)
            if key in ("A_x", "A_s", "S_w"):
                scale_key = "S_w" if key == "S_w" else "A_s"
                scale = abs(pt.get(scale_key, 0.0))
                unit = 10 ** (math.floor(math.log10(scale)) - 2) if scale else 0.0
                ok = abs(own - value) <= unit
            else:
                ok = math.isfinite(error) and error <= 1e-9
            status, reason = ("通过" if ok else "差异"), ""
        rows.append(
            {
                "case": name,
                "statistic": key,
                "openpt": own,
                "r": r,
                "pt13528": value,
                "pt13528_signed_t": pt.get("signed_" + key) if key.startswith("t_") else None,
                "relative_pt": error,
                "pt_status": status,
                "reason": reason,
                "r_status": source.get("status", "通过" if source.get("pass") else "差异"),
            }
        )
    summary = dict(Counter(row["pt_status"] for row in rows))
    (HERE / "threeway_random_report.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# 三路线固定种子随机基准",
        "",
        "同一 CSV 的 200 组数据；pt13528 未覆盖或返回错误时明确保留，不能视为通过。"
        "A/S 采用 equivalent-figure 停止规则，按显示位一末位比较，迭代次数单独比较；"
        "pt13528 的有符号 t 与 openpt、R 的 |t| 比较前取绝对值，原始符号保存在 JSON；"
        "其他数值采用 1e-9 相对容差。type 6 仅报告。R 端严格零值差异保留。",
        "",
        f"汇总：{json.dumps(summary, ensure_ascii=False)}。",
        "",
        "|数据集|统计量|openpt|R|pt13528|pt相对误差|pt结论|原因|R结论|",
        "|---|---|---:|---:|---:|---:|---|---|---|",
    ]
    for row in rows:

        def fmt(v: Any) -> str:
            return "—" if v is None else f"{v:.17g}"

        lines.append(
            f"|{row['case']}|{row['statistic']}|{fmt(row['openpt'])}|{fmt(row['r'])}|{fmt(row['pt13528'])}|{fmt(row['relative_pt'])}|{row['pt_status']}|{row['reason']}|{row['r_status']}|"
        )
    (HERE / "threeway_random_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return int(any(row["pt_status"] == "差异" for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
