# SPDX-License-Identifier: Apache-2.0
"""批量复核、新声称值及一对多打分映射。"""

from pathlib import Path

from openpyxl import load_workbook

from openpt.cli import main
from openpt.demo import _synthetic
from openpt.review.batch import write_xlsx
from openpt.review.compare import review


def test_new_claims_and_multiple_mapping() -> None:
    """NIQR、u(X)、z′、ζ、En 声称值均可比较。"""
    names = ["NIQR", "u(X)", "zprime:P", "zeta:P", "En:P"]
    data = {
        "config": {},
        "participants": [],
        "stability": {},
        "claims": [{"name": n, "value": 1.0, "digits": 1, "source": "合成"} for n in names],
    }
    result = {
        "中位数NIQR": {"niqr": 1},
        "指定值与不确定度": {"u": 1},
        "参加者统计量": {"P": {n: {"value": 1, "status": "OK"} for n in ("zprime", "zeta", "En")}},
    }
    rows = review(data, result, {"performance": ["条目A", "条目B"]})
    assert len(rows) == 5 and all(r["状态"] == "MATCH" for r in rows)
    assert all(r["评分条目"] == "条目A；条目B" for r in rows)


def test_batch_cli(tmp_path: Path) -> None:
    """两份虚构输入合并成可筛选工作表。"""
    first, second, output = (tmp_path / x for x in ("a.xlsx", "b.xlsx", "total.xlsx"))
    _synthetic(first)
    _synthetic(second)
    assert main(["review-batch", str(first), str(second), "--output", str(output)]) == 0
    ws = load_workbook(output)["差异总表"]
    assert ws.auto_filter.ref and ws.max_row > 2
    states = [row[0].value for row in list(ws.rows)[1:]]
    assert states == sorted(states, key={"DIFFERENCE": 0, "NOTE": 1, "MATCH": 2}.get)
    assert {row[2].value for row in list(ws.rows)[1:]} == {first.name, second.name}


def test_xlsx_text_formula_is_not_executed(tmp_path: Path) -> None:
    """声称来源等文本不应变成 Excel 公式。"""
    target = tmp_path / "safe.xlsx"
    write_xlsx(target, [{"状态": "NOTE", "项目": "=1+1"}])
    assert load_workbook(target).active["B2"].data_type == "s"
