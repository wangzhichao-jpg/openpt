# SPDX-License-Identifier: Apache-2.0
import pytest

from openpt.core.robust import algorithm_a
from openpt.core.stability import analyze
from openpt.review.compare import review, write_csv


# 合成样例，用于验证两种实验单位及复核分支；并非历史报告。
def test_review_branches(tmp_path):
    x = [[1, 2], [2, 3], [3, 4]]
    y = [[2, 3], [3, 4], [4, 5]]
    data = {
        "config": {"assigned": 2, "sigma": 1},
        "stability": {"基线": x, "稳定期": y},
        "participants": [{"id": "1", "value": 3}],
    }
    data["claims"] = [
        {"name": n, "value": v, "digits": 2, "source": "合成数据", "model": m}
        for n, v, m in [
            ("F", 1, "recommended"),
            ("Ss", 1, "recommended"),
            ("x*", 2, "recommended"),
            ("s*", 1, "recommended"),
            ("z:1", 1, "recommended"),
            ("t", 1, "repeats_pooled"),
            ("t", 1, "repeats_welch"),
            ("t", 1, "unknown"),
        ]
    ]
    result = {"均匀性": {"F": 1, "Ss": 1}, "算法A": {"x": 2, "s": 1}, "稳定性": analyze(x, y)}
    rows = review(data, result)
    assert len(rows) == 9
    assert next(row for row in rows if row["统计量"] == "z:1")["按推荐模型重算值"] == 1
    assert any(row["状态"] == "NOTE" and row["按报告模型复现值"] is None for row in rows)
    assert any("伪重复" in row["说明"] for row in rows)
    ranks = {"DIFFERENCE": 0, "NOTE": 1, "MATCH": 2}
    assert [ranks[row["状态"]] for row in rows] == sorted(ranks[row["状态"]] for row in rows)
    f = tmp_path / "review.csv"
    write_csv(f, rows)
    assert "按报告模型复现值" in f.read_text(encoding="utf-8-sig")
    data["claims"][0]["digits"] = "bad"
    with pytest.raises(ValueError):
        review(data, result)


def test_other_stop_rule_matching_is_not_value_mismatch():
    """合成数据：若简化法能复现，不得声称所有候选模型均不一致。"""
    values = [1, 2, 3, 4, 100]
    initial = algorithm_a(values, rule="simplified")
    recommended = algorithm_a(values, rule="gl002")
    data = {
        "config": {},
        "stability": {},
        "participants": [{"id": str(i), "value": v} for i, v in enumerate(values)],
        "claims": [
            {
                "name": "s*",
                "value": initial.s,
                "digits": 3,
                "source": "合成数据",
                "model": "recommended",
            }
        ],
    }
    rows = review(data, {"算法A": recommended})
    assert rows[0]["状态"] == "NOTE"
    assert "STOP_RULE_SENSITIVITY" in rows[0]["差异类型"]
    assert "VALUE_MISMATCH" not in rows[0]["差异类型"]


def test_no_candidate_matches_and_missing_composite_component():
    """合成数据：候选全部不符时列差异；缺少合成分量不能假设为零。"""
    values = [1, 2, 3, 4, 100]
    result = algorithm_a(values)
    data = {
        "config": {"sigma": 3, "sigma_composite": 4},
        "stability": {},
        "participants": [{"id": str(i), "value": v} for i, v in enumerate(values)],
        "claims": [
            {"name": "s*", "value": 999.0, "digits": 2, "source": "合成数据", "model": "absolute"}
        ],
    }
    rows = review(data, {"算法A": result})
    score = next(row for row in rows if row["统计量"] == "s*")
    assert score["状态"] == "DIFFERENCE" and "VALUE_MISMATCH" in score["差异类型"]
    composite = next(row for row in rows if row["统计量"] == "合成标准差")
    assert composite["状态"] == "NOTE" and "缺少样品间标准差" in composite["说明"]
