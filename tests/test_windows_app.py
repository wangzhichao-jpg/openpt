# SPDX-License-Identifier: Apache-2.0
"""窗口共用的业务适配层和甲醛示例。"""

from pathlib import Path

import pytest
from openpyxl import load_workbook

from openpt.windows_app import example_path, friendly_error, make_template, run_workbook, summarize


def test_example_chinese_path_and_results(tmp_path: Path) -> None:
    source = tmp_path / "中文 文件.xlsx"
    source.write_bytes(example_path().read_bytes())
    before = source.read_bytes()
    directory, data, result = run_workbook(source, tmp_path / "计算 结果")
    assert source.read_bytes() == before
    assert (directory / "report.docx").is_file()
    assert result["均匀性"]["Ss"] == pytest.approx(0.0642585921622)
    assert result["稳定性"]["difference"] == pytest.approx(0.12)
    assert result["其他稳定性"]["运输期"]["difference"] == pytest.approx(0.06)
    assert result["指定值与不确定度"]["value"] == pytest.approx(100.0405652277587)
    assert result["指定值与不确定度"]["u"] == pytest.approx(0.22326622377769484)
    summary = summarize(data, result)
    assert all(x in summary for x in ("甲醛样品", "稳定期", "运输期", "算法A", "0.223266"))


def test_template_has_no_measurements(tmp_path: Path) -> None:
    path = tmp_path / "模板.xlsx"
    make_template(path)
    book = load_workbook(path)
    assert all(book[name].max_row == 1 for name in ("均匀性", "稳定性", "参加者结果"))
    assert book["项目信息"]["B2"].value is None
    assert book["项目信息"]["B3"].value is None
    assigned = {row[0].value: row[1].value for row in book["指定值与不确定度"].iter_rows(min_row=2)}
    assert assigned["sigma_final"] is None and assigned["u_hom"] is None
    assert assigned["hom_mapping"] == "none"
    with pytest.raises(ValueError):
        make_template(example_path())


def test_short_validation_message() -> None:
    text = friendly_error(
        ValueError(
            '输入校验问题：[{"sheet":"均匀性","cell":"C2","message":"缺少数值","original":null}]'
        )
    )
    assert text == "均匀性 C2：缺少数值"


def test_missing_component_and_period_names() -> None:
    text = summarize(
        {},
        {
            "稳定性时间组": "第7天",
            "稳定性": {
                "method": "mean_difference",
                "difference": 1,
                "threshold": 2,
                "mean_difference_pass": True,
            },
        },
    )
    assert "第7天" in text and "稳定期" not in text
    assert "均匀性：未计算" in text and "指定值：未计算" in text
