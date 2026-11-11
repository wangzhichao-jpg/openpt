# SPDX-License-Identifier: Apache-2.0
"""指定值输入到统计表、计算书、复核的端到端测试。"""

import json
from pathlib import Path

from docx import Document
from openpyxl import load_workbook

from openpt.cli import main
from openpt.io.excel import template


def make_input(path: Path, duplicate: bool = False) -> None:
    """生成完全虚构的参考定值及不确定度数据。"""
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "虚构项目"
    book["项目信息"]["B3"] = "mg/kg"
    book["方法配置"]["B17"] = "all"
    ws = book["指定值与不确定度"]
    fields = {ws.cell(row, 1).value: row for row in range(2, ws.max_row + 1)}
    for key, value in {
        "method": "certified",
        "value": 100,
        "uncertainty": 1,
        "source": "虚构证书",
        "uncertainty_source": "虚构预算",
        "sigma_temporary": 4,
        "sigma_final": 5,
        "sigma_procedure": "预先设定",
        "hom_mapping": "both" if duplicate else "none",
        "u_hom": 0.2,
        "U_assigned": 2,
        "k_assigned": 2,
        "independent": True,
    }.items():
        ws.cell(fields[key], 2, value)
    for i, value in enumerate([101, 102, 103], 1):
        book["参加者结果"].append([f"P{i}", value, "mg/kg", 1.5, 3, 2])
    book["报告声称值"].append(["zprime:P1", 0.20, 2, "虚构声称", "recommended", None])
    book.save(path)


def test_workflow(tmp_path: Path) -> None:
    """模板、六类统计量及出处均进入 JSON 和计算书。"""
    path = tmp_path / "input.xlsx"
    make_input(path)
    assert main(["review", str(path)]) == 0
    result = json.loads((tmp_path / "input_结果.json").read_text(encoding="utf-8"))
    assigned = result["指定值与不确定度"]
    scores = result["参加者统计量"]["P1"]
    assert assigned["status"] == "OK" and assigned["value"] == 100
    assert all(scores[k]["status"] == "OK" for k in ("zprime", "zeta", "En"))
    doc = Document(tmp_path / "input_计算书.docx")
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "指定值与不确定度" in text and "GL002 4.4.1.3" in text
    entries = {
        row.cells[0].text: row.cells[1].text
        for table in doc.tables
        for row in table.rows
        if len(row.cells) == 2
    }
    assert entries["基础值含均匀性分量"] == "否"
    assert entries["结果间不相关"] == "是"


def test_workbook_expert_consensus(tmp_path: Path) -> None:
    """模板中专家结果的字符串正确转换，均值及标准误输出全精度。"""
    path = tmp_path / "expert.xlsx"
    make_input(path)
    book = load_workbook(path)
    sheet = book["指定值与不确定度"]
    fields = {sheet.cell(row, 1).value: row for row in range(2, sheet.max_row + 1)}
    sheet.cell(fields["method"], 2, "expert_consensus")
    sheet.cell(fields["value"], 2).value = None
    sheet.cell(fields["uncertainty"], 2).value = None
    sheet.cell(fields["expert_values"], 2, "99,100,101")
    book.save(path)
    assert main(["run", str(path)]) == 0
    result = json.loads((tmp_path / "expert_结果.json").read_text(encoding="utf-8"))
    assert result["指定值与不确定度"]["value"] == 100
    assert result["指定值与不确定度"]["expert_values"] == [99, 100, 101]


def test_single_participant_en(tmp_path: Path) -> None:
    """测量审核单个参加者可计算 En，稳健统计单独标记未评价。"""
    path = tmp_path / "one.xlsx"
    make_input(path)
    book = load_workbook(path)
    book["参加者结果"].delete_rows(3, 2)
    book.save(path)
    assert main(["run", str(path)]) == 0
    result = json.loads((tmp_path / "one_结果.json").read_text(encoding="utf-8"))
    assert result["参加者统计量"]["P1"]["En"]["status"] == "OK"
    assert result["稳健统计状态"].startswith("NOT_EVALUATED")


def test_duplicate_blocks_all_scores(tmp_path: Path) -> None:
    """重复分配时不能输出任何能力评价结论。"""
    path = tmp_path / "input.xlsx"
    make_input(path, duplicate=True)
    assert main(["run", str(path)]) == 0
    result = json.loads((tmp_path / "input_结果.json").read_text(encoding="utf-8"))
    assert result["指定值与不确定度"]["status"] == "DESIGN_REVIEW"
    assert all(
        s["value"] is None and s["classification"] is None
        for scores in result["参加者统计量"].values()
        for s in scores.values()
    )
