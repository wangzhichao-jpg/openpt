# SPDX-License-Identifier: Apache-2.0
"""面向实验室用户的命令和模板测试。"""

from pathlib import Path

from openpyxl import load_workbook

from openpt.cli import main
from openpt.io.excel import read_workbook, template


def test_chinese_template(tmp_path: Path) -> None:
    """模板说明、下拉选项和英文配置键映射。"""
    path = tmp_path / "blank.xlsx"
    template(path)
    book = load_workbook(path)
    assert "填写说明" in book.sheetnames
    assert len(book["方法配置"].data_validations.dataValidation) == 3
    book["项目信息"]["B2"] = "合成项目"
    book["项目信息"]["B3"] = "mg/kg"
    book["方法配置"]["B4"] = "启用"
    book["方法配置"]["B5"] = "单均值"
    book.save(path)
    config = read_workbook(path)["config"]
    assert config["strict_homogeneity"] is True
    assert config["stability_method"] == "one_sample"


def test_demo_and_default_output(tmp_path: Path, monkeypatch) -> None:
    """在无外部 PDF 转换器时，演示仍生成输入和计算书。"""
    monkeypatch.setattr("openpt.demo.shutil.which", lambda name: None)
    assert main(["demo", str(tmp_path)]) == 0
    for filename in [
        "GL003_A1.xlsx",
        "GL003_A1_计算书.docx",
        "GL003_A1_结果.json",
        "synthetic_review_计算书.docx",
        "synthetic_review_差异.csv",
    ]:
        assert (tmp_path / filename).is_file()
