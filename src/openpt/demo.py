# SPDX-License-Identifier: Apache-2.0
"""生成公开标准示例和完全虚构的复核示例。"""

import json
import shutil
import subprocess
from importlib.resources import files
from pathlib import Path

from openpyxl import load_workbook

from .io.excel import template


def _a1(path: Path) -> None:
    """GL003 附录 A.1 表1、2。"""
    data = json.loads(files("openpt.config").joinpath("demo.json").read_text(encoding="utf-8"))
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "GL003 A.1"
    book["项目信息"]["B3"] = "mg/kg"
    for i, row in enumerate(data["a1"], 1):
        for j, value in enumerate(row, 1):
            book["均匀性"].append([str(i), str(j), value, "mg/kg"])
    book.save(path)


def _synthetic(path: Path) -> None:
    """构造虚构的多时点、参加者和报告模型。"""
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "虚构演示"
    book["项目信息"]["B3"] = "mg/kg"
    groups: dict[str, list[list[float]]] = {
        "基线": [[100 + i, 101 + i] for i in range(10)],
        "稳定期": [[104.0, 104.8], [105.0, 105.3], [106.0, 105.6]],
        "后期": [[103.0, 104.0], [104.5, 104.7], [105.2, 105.4]],
    }
    for group, items in groups.items():
        for i, row in enumerate(items, 1):
            for j, value in enumerate(row, 1):
                book["稳定性"].append([group, str(i), str(j), value, "mg/kg"])
                if group == "基线":
                    book["均匀性"].append([str(i), str(j), value, "mg/kg"])
    for config_row in [
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
        book["方法配置"].append(config_row)
    for model, group in [
        ("repeats_pooled", "稳定期"),
        ("displayed_summary", "稳定期"),
        ("repeats_welch", "后期"),
    ]:
        book["报告声称值"].append(["t", 0.10, 2, "虚构数据", model, group])
    book["参加者结果"].append(["P1", 106.0, "mg/kg"])
    book["参加者结果"].append(["P2", 105.0, "mg/kg"])
    book["报告声称值"].append(["z:P1", 0.0, 1, "虚构数据", "recommended", None])
    book.save(path)


def create_demo(directory: Path) -> None:
    """生成输入、计算书、JSON 和复核差异；可选转换 PDF。"""
    from .cli import main

    directory.mkdir(parents=True, exist_ok=True)
    a1 = directory / "GL003_A1.xlsx"
    synthetic = directory / "synthetic_review.xlsx"
    _a1(a1)
    _synthetic(synthetic)
    if main(
        [
            "run",
            str(a1),
            "--runs-dir",
            str(directory / "runs"),
            "--docx",
            str(directory / "GL003_A1_计算书.docx"),
            "--json",
            str(directory / "GL003_A1_结果.json"),
        ]
    ) or main(
        [
            "review",
            str(synthetic),
            "--runs-dir",
            str(directory / "runs"),
            "--docx",
            str(directory / "synthetic_review_计算书.docx"),
            "--json",
            str(directory / "synthetic_review_结果.json"),
            "--differences",
            str(directory / "synthetic_review_差异.csv"),
        ]
    ):
        raise ValueError("示例计算失败")
    converter = shutil.which("soffice")
    if converter:
        documents = [directory / "GL003_A1_计算书.docx", directory / "synthetic_review_计算书.docx"]
        try:
            subprocess.run(
                [
                    converter,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(directory),
                    *(str(p) for p in documents),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise ValueError(f"PDF 转换失败，DOCX 已生成：{exc}") from exc
    else:
        print("未找到 LibreOffice，已生成 DOCX；PDF 需另行转换。")
