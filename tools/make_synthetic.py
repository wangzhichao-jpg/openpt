# SPDX-License-Identifier: Apache-2.0
"""生成完全虚构的复核输入，不读取任何历史资料。"""

from pathlib import Path

from openpyxl import load_workbook

from openpt.io.excel import template


def main():
    path = Path(__file__).resolve().parents[1] / "examples" / "synthetic_review.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "虚构演示"
    book["项目信息"]["B3"] = "mg/kg"
    baseline = [[100 + i, 101 + i] for i in range(10)]
    follow = [[104.0, 104.8], [105.0, 105.3], [106.0, 105.6]]
    later = [[103.0, 104.0], [104.5, 104.7], [105.2, 105.4]]
    for group, items in [("基线", baseline), ("稳定期", follow), ("后期", later)]:
        for i, row in enumerate(items, 1):
            for j, value in enumerate(row, 1):
                book["稳定性"].append([group, str(i), str(j), value, "mg/kg"])
                if group == "基线":
                    book["均匀性"].append([str(i), str(j), value, "mg/kg"])
    for row in [
        ("mean1", 105.0),
        ("mean2", 105.12),
        ("s1", 3.03),
        ("s2", 0.60),
        ("n1", 10),
        ("n2", 3),
        ("sigma", 5.0),
        ("sigma_pt", 5.1),
        ("assigned", 105.0),
        ("sigma_ss", 1.0),
        ("sigma_composite", 5.1),
        ("reported_stability_sigma", 5.1),
    ]:
        book["方法配置"].append(row)
    for model in ("repeats_pooled", "displayed_summary"):
        book["报告声称值"].append(["t", 0.10, 2, "虚构示例，非历史报告", model, "稳定期"])
    book["报告声称值"].append(["t", 0.10, 2, "虚构示例，非历史报告", "repeats_welch", "后期"])
    book["参加者结果"].append(["P1", 106.0, "mg/kg"])
    book["参加者结果"].append(["P2", 105.0, "mg/kg"])
    book["报告声称值"].append(["z:P1", 0.0, 1, "虚构示例，非历史报告", "recommended", None])
    book.save(path)


if __name__ == "__main__":
    main()
