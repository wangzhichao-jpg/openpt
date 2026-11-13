# SPDX-License-Identifier: Apache-2.0
"""核心结果摘要与单测方法配置。"""

from pathlib import Path

import pytest
from docx import Document

from openpt.cli import calculate
from openpt.report.docx import make_report


def _text(path: Path) -> str:
    doc = Document(path)
    return "\n".join(
        [p.text for p in doc.paragraphs]
        + [c.text for table in doc.tables for row in table.rows for c in row.cells]
    )


def test_missing_core_items_are_listed_without_blocking(tmp_path: Path) -> None:
    result = {"指定值与不确定度": {"method": "known", "value": 10, "u": 0.2, "status": "OK"}}
    path = tmp_path / "report.docx"
    make_report(path, {"info": {"单位": "mg"}, "config": {}}, result)
    text = _text(path)
    assert "未提供均匀性数据" in text and "未提供稳定性数据" in text
    assert "没有未评价或需设计审查的条目" not in text
    assert "已知值；外部已评定值登记" in text
    assert "X=10 mg" in text and "u(X)=0.2000 mg" in text and "状态：OK" in text


def test_consensus_summary_and_unavailable_u(tmp_path: Path) -> None:
    result = {
        "指定值与不确定度": {
            "method": "participant_consensus",
            "consensus_method": "robust_mean",
            "value": 100.123456,
            "u": None,
            "status": "DESIGN_REVIEW",
        }
    }
    path = tmp_path / "report.docx"
    make_report(path, {"info": {"单位": "mg"}, "config": {}}, result)
    text = _text(path)
    assert "参加者公议；程序计算（robust_mean）" in text
    assert "X=100.1 mg" in text and "u(X)=未评价" in text
    assert "状态：DESIGN_REVIEW" in text


@pytest.mark.parametrize("criterion", ["f_test", "ss_0.3sigma", "both"])
def test_single_rejects_explicit_gl003_criterion(criterion: str) -> None:
    data = {
        "config": {"replicate_type": "single", "gl003_hom_criterion": criterion, "sigma": 1},
        "homogeneity": [[1.0], [1.1], [1.2]],
        "stability": {},
        "participants": [],
    }
    with pytest.raises(ValueError, match=r"B\.1\.2.*不支持 GL003"):
        calculate(data)


def test_single_method_table_is_not_gl003_anova(tmp_path: Path) -> None:
    data = {
        "info": {"单位": "mg"},
        "config": {"replicate_type": "single", "sigma": 1},
        "homogeneity": [[1.0], [1.1], [1.2]],
        "stability": {},
        "participants": [],
    }
    result = calculate(data)
    path = tmp_path / "report.docx"
    make_report(path, data, result)
    text = _text(path)
    assert "单测标准差：GB/T 28043-2019 B.1.2" in text
    assert "单测标准差法，不计算 GL003 4.2/4.3" in text
    assert "均匀性单测例外采用 GB/T 28043-2019 B.1.2" in text
    assert "GL003 4.2 F 检验为主" not in text
