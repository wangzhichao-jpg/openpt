# SPDX-License-Identifier: Apache-2.0
"""窗口共用的业务适配层和甲醛示例。"""

import runpy
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
    assert all(x in summary for x in ("甲醛样品", "稳定期", "运输期", "算法A稳健公议", "0.223266"))


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


def test_smoke_launch_records_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import openpt.windows_app as app

    def fail() -> None:
        raise RuntimeError("smoke diagnostic")

    monkeypatch.setenv("OPENPT_GUI_SMOKE_DIR", str(tmp_path))
    monkeypatch.setattr(app, "main", fail)
    launch = Path(__file__).resolve().parents[1] / "windows" / "launch.py"
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(launch), run_name="__main__")
    assert exc.value.code == 1
    assert "smoke diagnostic" in (tmp_path / "gui-smoke-error.txt").read_text(encoding="utf-8")


def test_transfer_and_gbt_summary() -> None:
    text = summarize(
        {},
        {
            "传递标准稳定性": {
                "STD1|P1": {
                    "standard": "STD1",
                    "delta_max": 0.3,
                    "unit": "V",
                    "criteria": [{"kind": "fixed", "value": 0.3, "limit": 1, "pass": True}],
                },
            },
        },
    )
    assert "单台传递标准：不适用样品间均匀性检验" in text
    assert "Δmax = 0.3 V" in text and "限值 = 1；通过" in text
    assert "稳定性：未计算" not in text
    gbt = summarize(
        {},
        {
            "均匀性": {"conclusion": False},
            "GB/T均匀性": {"ss": 1, "selected_rule": "basic", "basic_limit": 2, "conclusion": True},
            "稳定性": {"pass": False},
            "GB/T稳定性": {"稳定期": {"difference": 0.1, "basic_limit": 0.2, "conclusion": True}},
        },
    )
    assert "GB/T 28043 B.2.2" in gbt and "GB/T 28043 B.5.1" in gbt
    assert "未通过" not in gbt


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
