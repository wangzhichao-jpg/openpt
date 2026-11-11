# SPDX-License-Identifier: Apache-2.0
"""对公开 B1 与合成示例追加 pt13528 同输入路线。"""

import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from pt13528.homogeneity import homogeneity, stability_t_test
from pt13528.robust import algorithm_a, median, niqr
from pt13528.scores import en_score, z_prime_score, z_score, zeta_score

from openpt.cli import calculate
from openpt.io.excel import read_workbook

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent / "examples"


def compare(
    name: str,
    scope: str,
    key: str,
    own: float | None,
    r: float,
    pt: float | None,
    reason: str = "",
    unit: float | None = None,
) -> dict[str, Any]:
    if pt is None or own is None:
        return {
            "case": name,
            "scope": scope,
            "statistic": key,
            "openpt": own,
            "r": r,
            "pt13528": pt,
            "relative_pt": None,
            "status": "仅报告" if own is None else "pt13528 未覆盖",
            "reason": reason,
        }
    error = abs(own - pt) / max(abs(own), abs(pt)) if own or pt else 0.0
    ok = abs(own - pt) <= unit if unit is not None else math.isfinite(error) and error <= 1e-9
    return {
        "case": name,
        "scope": scope,
        "statistic": key,
        "openpt": own,
        "r": r,
        "pt13528": pt,
        "relative_pt": error,
        "status": "通过" if ok else "差异",
        "reason": reason,
    }


def main() -> int:
    rows = []
    b1 = json.loads((HERE / "r/b1_cases.json").read_text(encoding="utf-8"))
    b1_results = json.loads((HERE / "b1_report.json").read_text(encoding="utf-8"))
    for row in b1_results:
        name, key = row["case"], row["statistic"]
        if name.startswith("示例/"):
            d = read_workbook(EXAMPLES / name.removeprefix("示例/"))
            values = [p["value"] for p in d["participants"]]
        else:
            values = b1[name]
        a = algorithm_a(values, tol="equivalent-figure")
        pt = {
            "A_x": a["location"],
            "A_s": a["scale"],
            "A_iterations": a["iterations"],
            "median": median(values),
            "niqr": niqr(values, quantile_method="linear"),
        }
        scale = abs(a["scale"])
        unit = 10 ** (math.floor(math.log10(scale)) - 2) if scale else 0.0
        rows.append(
            compare(
                name,
                "稳健统计",
                key,
                row["openpt"],
                row["r"],
                pt.get(key),
                "type 6 仅供参考" if key.endswith("type6") else "",
                unit if key in ("A_x", "A_s") else None,
            )
        )
    examples = json.loads((HERE / "examples_report.json").read_text(encoding="utf-8"))
    cache = {}
    for row in examples:
        name, scope, key = row["case"], row["group"], row["statistic"]
        if name not in cache:
            data = read_workbook(EXAMPLES / name)
            cache[name] = (data, calculate(data, review_mode=True))
        data, result = cache[name]
        value = None
        reason = "接口未提供该统计量"
        if scope == "均匀性":
            h = homogeneity(data["homogeneity"])
            value = {"F": h.f_statistic, "Ss": h.s_s}.get(key)
        elif scope.endswith("/单元均值"):
            label = scope.removesuffix("/单元均值")
            x = [statistics.mean(g) for g in data["stability"]["基线"]]
            y = [statistics.mean(g) for g in data["stability"][label]]
            pooled = stability_t_test(x, y, equal_var=True)
            welch = stability_t_test(x, y, equal_var=False)
            t = {}
            for tag, each in [("pooled", pooled), ("welch", welch)]:
                t.update({f"t_{tag}": abs(each[0]), f"df_{tag}": each[1], f"p_{tag}": each[2]})
            value = t.get(key)
            reason = "有符号 t 按绝对值比较" if key.startswith("t_") else ""
        else:
            participant = next(p for p in data["participants"] if p["id"] == scope)
            a = result.get("指定值与不确定度")
            cfg = data["config"]
            if a:
                x, X, sigma = participant["value"], a["value"], a["sigma_prime"]
                methods = {
                    "z": z_score(x, X, sigma),
                    "zprime": z_prime_score(x, X, sigma, a["u"]),
                    "zeta": zeta_score(x, X, participant["u"], a["u"]),
                    "En": en_score(x, X, participant["U"], a["U_assigned"]),
                }
                value = methods[key]
            else:
                value = (
                    z_score(participant["value"], cfg["assigned"], cfg["sigma_pt"])
                    if key == "z"
                    else None
                )
            reason = "指定值与不确定度沿用 openpt 计算值，定值预算未独立验证"
        rows.append(compare(name, scope, key, row["openpt"], row["r"], value, reason))
    summary = dict(Counter(row["status"] for row in rows))
    (HERE / "threeway_examples_report.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# 公开 B1 与示例三路线对照",
        "",
        "使用相同输入；pt13528 和 openpt 共用 SciPy。缺失接口和 type 6 单独列出；"
        "稳健量采用对应位停止规则与显示位一末位容差。",
        f"汇总：{json.dumps(summary, ensure_ascii=False)}。",
        "",
        "|数据集|范围|统计量|openpt|R|pt13528|相对误差|结论|说明|",
        "|---|---|---|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:

        def fmt(v: Any) -> str:
            return "—" if v is None else f"{v:.17g}"

        lines.append(
            f"|{row['case']}|{row['scope']}|{row['statistic']}|{fmt(row['openpt'])}|{fmt(row['r'])}|{fmt(row['pt13528'])}|{fmt(row['relative_pt'])}|{row['status']}|{row['reason']}|"
        )
    (HERE / "threeway_examples_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return int(any(row["status"] == "差异" for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
