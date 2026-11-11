# SPDX-License-Identifier: Apache-2.0
"""生成完全虚构的指定值和能力统计量公开示例。"""

import math
from pathlib import Path

from openpyxl import load_workbook

from openpt.cli import main
from openpt.io.excel import template


def generate(directory: Path) -> None:
    """生成 Excel、DOCX、JSON；覆盖 z′、ζ 和 En。"""
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "assigned_value_scores.xlsx"
    template(source)
    book = load_workbook(source)
    book["项目信息"]["B2"] = "虚构指定值演示"
    book["项目信息"]["B3"] = "mg/kg"
    book["方法配置"]["B17"] = "all"
    sheet = book["指定值与不确定度"]
    rows = {sheet.cell(i, 1).value: i for i in range(2, sheet.max_row + 1)}
    for key, value in {
        "method": "certified",
        "value": 100,
        "uncertainty": 1,
        "source": "虚构参考证书",
        "uncertainty_source": "虚构标准不确定度预算",
        "sigma_temporary": 4,
        "sigma_final": 5,
        "sigma_procedure": "虚构的预设程序",
        "u_hom": 0.2,
        "hom_mapping": "assigned",
        "U_assigned": 2 * math.hypot(1, 0.2),
        "k_assigned": 2,
        "independent": True,
    }.items():
        sheet.cell(rows[key], 2, value)
    for index, value in enumerate((99, 101, 103), 1):
        book["参加者结果"].append([f"P{index}", value, "mg/kg", 1.5, 3.0, 2])
    book.save(source)
    code = main(
        [
            "run",
            str(source),
            "--docx",
            str(directory / "assigned_value_scores.docx"),
            "--json",
            str(directory / "assigned_value_scores.json"),
        ]
    )
    if code:
        raise RuntimeError("示例生成失败")


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1] / "examples")
