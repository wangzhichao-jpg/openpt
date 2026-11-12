# SPDX-License-Identifier: Apache-2.0
"""指定值输入到统计表、计算书、复核的端到端测试。"""

import json
from pathlib import Path

import pytest
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


@pytest.mark.parametrize("rule", ["absolute", "simplified"])
def test_consensus_uses_selected_algorithm_rule(tmp_path: Path, rule: str) -> None:
    """公议值与显示的算法 A 必须使用同一停止规则。"""
    path = tmp_path / "consensus.xlsx"
    make_input(path)
    book = load_workbook(path)
    book["方法配置"]["B9"] = rule
    sheet = book["指定值与不确定度"]
    fields = {sheet.cell(row, 1).value: row for row in range(2, sheet.max_row + 1)}
    sheet.cell(fields["method"], 2, "participant_consensus")
    sheet.cell(fields["value"], 2).value = None
    sheet.cell(fields["uncertainty"], 2).value = None
    participants = book["参加者结果"]
    participants.delete_rows(2, participants.max_row - 1)
    for i, value in enumerate([1, 2, 3, 4, 5, 6, 7, 8, 9, 100], 1):
        participants.append([f"P{i}", value, "mg/kg"])
    book.save(path)
    assert main(["run", str(path)]) == 0
    result = json.loads((tmp_path / "consensus_结果.json").read_text(encoding="utf-8"))
    assigned, robust = result["指定值与不确定度"], result["算法A"]
    assert robust["rule"] == assigned["consensus_algorithm_rule"] == rule
    assert assigned["value"] == robust["x"]
    assert assigned["base_u"] == pytest.approx(robust["u_x"], rel=1e-15)
    doc = Document(tmp_path / "consensus_计算书.docx")
    assert any(c.text == "公议算法 A 停止规则" for t in doc.tables for r in t.rows for c in r.cells)


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


def test_transport_uncertainty_workbook(tmp_path: Path) -> None:
    """运输分量可追溯地进入 u(X)，重复声明时阻断评价。"""
    path = tmp_path / "transport.xlsx"
    make_input(path)
    book = load_workbook(path)
    sheet = book["指定值与不确定度"]
    fields = {sheet.cell(row, 1).value: row for row in range(2, sheet.max_row + 1)}
    sheet.cell(fields["u_trans"], 2, 2.0)
    sheet.cell(fields["trans_mapping"], 2, "assigned")
    book.save(path)
    assert main(["run", str(path)]) == 0
    result = json.loads((tmp_path / "transport_结果.json").read_text(encoding="utf-8"))
    assert result["指定值与不确定度"]["u"] == 5**0.5
    assert result["指定值与不确定度"]["trans_mapping"] == "assigned"
    book = load_workbook(path)
    book["指定值与不确定度"].cell(fields["trans_in_base"], 2, "TRUE")
    book.save(path)
    assert main(["run", str(path)]) == 0
    result = json.loads((tmp_path / "transport_结果.json").read_text(encoding="utf-8"))
    assert result["指定值与不确定度"]["status"] == "DESIGN_REVIEW"
    assert all(score["value"] is None for score in result["参加者统计量"]["P1"].values())


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
