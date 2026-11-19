# SPDX-License-Identifier: Apache-2.0
"""逐组准则仅在设置时进入窗口与计算书。"""

import copy
import json
from pathlib import Path

import pytest
from docx import Document

from openpt.cli import calculate
from openpt.io.excel import read_workbook
from openpt.report.docx import make_report
from openpt.windows_app import summarize

EXAMPLE = Path(__file__).resolve().parents[1] / "windows/examples/GB-T合成检测.xlsx"


def doc_text(path: Path) -> str:
    doc = Document(path)
    return "\n".join(
        [p.text for p in doc.paragraphs]
        + [c.text for table in doc.tables for row in table.rows for c in row.cells]
    )


@pytest.mark.parametrize("standard", ["gbt28043", "gl003"])
@pytest.mark.parametrize("overrides", [False, True])
def test_period_display(tmp_path: Path, standard: str, overrides: bool) -> None:
    data = read_workbook(EXAMPLE)
    data["stability"]["运输期"] = copy.deepcopy(data["stability"]["稳定期"])
    data["config"]["criterion_standard"] = standard
    data["config"]["stability_method"] = "two_sample"
    if standard == "gl003":
        data["assigned_config"]["hom_source"] = "manual"
    if overrides:
        options = (
            {
                "稳定期": {"rule": "basic"},
                "运输期": {"rule": "extended", "kind": "transport", "u2": 0.5},
            }
            if standard == "gbt28043"
            else {
                "稳定期": {"stability_method": "two_sample", "baseline_source": "baseline_group"},
                "运输期": {"stability_method": "mean_difference", "baseline_source": "homogeneity"},
            }
        )
        data["config"]["stability_period_options"] = json.dumps(options, ensure_ascii=False)
        if standard == "gbt28043":
            data["config"]["stability_u1"] = 0.5
    result = calculate(data)
    summary = summarize(data, result)
    path = tmp_path / "report.docx"
    make_report(path, data, result)
    text = doc_text(path)
    if not overrides:
        assert "（逐组设置）" not in summary
        assert "逐组评价准则" not in text
        without_metadata = copy.deepcopy(result)
        for item in [
            without_metadata.get("稳定性", {}),
            *without_metadata.get("其他稳定性", {}).values(),
            *without_metadata.get("GB/T稳定性", {}).values(),
        ]:
            item.pop("criterion_settings", None)
        assert summarize(data, without_metadata) == summary
        return
    assert "逐组评价准则" in text
    for name in ("稳定期", "运输期"):
        line = next(line for line in summary.splitlines() if line.startswith(name + "（"))
        assert all(token in line for token in ("方法=", "判据=", "依据=", "基线="))
        assert name in text
    assert all(
        field in text for field in ("判据规则", "依据", "δE", "基线来源", "各项来源", "逐组设置")
    )
    if standard == "gbt28043":
        assert "基本判据（逐组设置）" in summary
        assert "扩展判据（逐组设置）" in summary
        assert "运输（逐组设置）" in text
        assert "方法：标准模式" in text
    else:
        assert "均值差法（逐组设置）" in summary
        assert "均匀性数据（逐组设置）" in summary
        assert "两样本 t 检验（逐组设置）" in summary
        assert "判据规则：由方法确定；依据：由方法确定" in text


def test_only_overridden_fields_are_annotated() -> None:
    data = read_workbook(EXAMPLE)
    data["stability"]["运输期"] = copy.deepcopy(data["stability"]["稳定期"])
    data["config"]["stability_period_options"] = '{"运输期":{"rule":"extended","u2":0.5}}'
    data["config"]["stability_u1"] = 0.5
    summary = summarize(data, calculate(data))
    stable = next(line for line in summary.splitlines() if line.startswith("稳定期（"))
    transport = next(line for line in summary.splitlines() if line.startswith("运输期（"))
    assert "（逐组设置）" not in stable
    assert "扩展判据（逐组设置）" in transport
    assert "依据=σ_pt（逐组设置）" not in transport


def test_delta_e_basis_is_visible(tmp_path: Path) -> None:
    data = read_workbook(EXAMPLE)
    data["stability"]["运输期"] = copy.deepcopy(data["stability"]["稳定期"])
    data["config"]["stability_period_options"] = '{"运输期":{"basis":"delta_e","delta_e":50}}'
    result = calculate(data)
    summary = summarize(data, result)
    assert "依据=δE（逐组设置）；δE=50.00（逐组设置）" in summary
    path = tmp_path / "delta.docx"
    make_report(path, data, result)
    assert "50.00（逐组设置）" in doc_text(path)


def test_one_sample_does_not_claim_a_baseline(tmp_path: Path) -> None:
    data = read_workbook(EXAMPLE)
    data["config"].update(
        {
            "criterion_standard": "gl003",
            "reference": 100,
            "stability_period_options": '{"稳定期":{"stability_method":"one_sample"}}',
        }
    )
    data["assigned_config"]["hom_source"] = "manual"
    result = calculate(data)
    assert "基线=不适用（单样本使用参考值）" in summarize(data, result)
    path = tmp_path / "single.docx"
    make_report(path, data, result)
    assert "不适用（单样本使用参考值）" in doc_text(path)
