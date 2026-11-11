# SPDX-License-Identifier: Apache-2.0
"""列映射和 CSV 实际进入计算，不改原始文件。"""

import json
from pathlib import Path

from openpyxl import load_workbook

from openpt.cli import main
from openpt.io.excel import read_workbook, template


def test_mapped_workbook_and_sources(tmp_path: Path) -> None:
    """重排列并重命名后，来源仍指向原始单元格。"""
    path = tmp_path / "input.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "测试"
    book["项目信息"]["B3"] = "mg"
    ws = book["均匀性"]
    ws.delete_rows(1)
    ws.append(["读数", "样品", "次数", "单位"])
    for sample in (1, 2):
        for repeat in (1, 2):
            ws.append([sample + repeat / 10, sample, repeat, "mg"])
    book.save(path)
    mapping = {"均匀性": {"单元编号": "样品", "重复编号": "次数", "值": "读数"}}
    data = read_workbook(path, mapping)
    assert data["sources"] == ["均匀性!A2", "均匀性!A3", "均匀性!A4", "均匀性!A5"]
    assert data["homogeneity"] == [[1.1, 1.2], [2.1, 2.2]]
    columns = tmp_path / "columns.json"
    columns.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    original = path.read_bytes()
    assert main(["run", str(path), "--columns", str(columns)]) == 0
    assert path.read_bytes() == original


def test_csv_calculation_and_encoding(tmp_path: Path, capsys: object) -> None:
    """CSV 按明确编码导入并作为测量值计算。"""
    path = tmp_path / "input.csv"
    path.write_text(
        "单元编号,重复编号,值,单位\n1,1,1.1,毫克\n1,2,1.2,毫克\n2,1,2.1,毫克\n2,2,2.2,毫克\n",
        encoding="gbk",
    )
    assert main(["run", str(path), "--unit", "毫克"]) == 2
    assert main(["run", str(path), "--unit", "毫克", "--encoding", "gbk"]) == 0
    assert read_workbook(path, encoding="gbk", unit="毫克")["sources"][0] == "均匀性!C2"
