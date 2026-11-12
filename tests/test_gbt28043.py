# SPDX-License-Identifier: Apache-2.0
"""附录 B 的公开合成数据、边界和内部例题测试。"""

import csv
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from docx import Document
from openpyxl import load_workbook
from scipy.stats import chi2, f

from openpt.cli import calculate
from openpt.core.gbt28043 import homogeneity, period_options, stability
from openpt.errors import InputError
from openpt.io.excel import read_workbook, template
from openpt.report.docx import make_report
from openpt.review.compare import review


def test_homogeneity_basic_and_repeatability() -> None:
    data = [[float(i), float(i)] for i in range(10)]
    h = homogeneity(data, 10)
    assert h["sx"] == pytest.approx(math.sqrt(110 / 12))
    assert h["sw"] == 0
    assert h["ss"] == pytest.approx(h["sx"])
    assert h["basic_pass"] is False
    assert h["repeatability_check"] is True
    assert h["f1"] == pytest.approx(chi2.ppf(0.95, 9) / 9)
    assert h["f2_or_fm"] == pytest.approx((f.ppf(0.95, 9, 10) - 1) / 2)
    assert h["extended_pass"] is True


def test_homogeneity_zero_and_outside_table() -> None:
    result = homogeneity([[0, 2], [0, 2]], 1)
    assert result["variance_raw"] < 0
    assert result["ss"] == 0
    assert result["basic_pass"] is True
    assert result["repeatability_check"] is False
    assert result["extended_pass"] is None
    assert homogeneity([[0, 0]] * 21, 1)["f1"] is None
    assert homogeneity([[0, 0]] * 10, None)["basic_pass"] is None
    with pytest.raises(InputError):
        homogeneity([[1, 2], [3]], 1)
    with pytest.raises(InputError, match="溢出"):
        homogeneity([[0, 0]] * 10, 1e308)


@pytest.mark.parametrize("g, available", [(6, False), (7, True), (20, True), (21, False)])
def test_extended_table_boundaries(g: int, available: bool) -> None:
    result = homogeneity([[float(i), float(i)] for i in range(g)], 1)
    assert (result["extended_pass"] is not None) is available
    assert bool(result["f1"] is not None) is available


def test_homogeneity_criterion_boundaries() -> None:
    data = [[float(i), float(i)] for i in range(10)]
    reference = homogeneity(data, 1)
    ss = reference["ss"]
    basic_sigma = ss / 0.3
    assert homogeneity(data, basic_sigma * (1 - 1e-8))["basic_pass"] is False
    assert homogeneity(data, basic_sigma)["basic_pass"] is True
    assert homogeneity(data, basic_sigma * (1 + 1e-8))["basic_pass"] is True
    extended_sigma = ss / (0.3 * math.sqrt(reference["f1"]))
    assert homogeneity(data, extended_sigma * (1 - 1e-8))["extended_pass"] is False
    assert homogeneity(data, extended_sigma)["extended_pass"] is True
    assert homogeneity(data, extended_sigma * (1 + 1e-8))["extended_pass"] is True
    repeat = 0.5 / math.sqrt(2)
    assert homogeneity([[-repeat, repeat]] * 10, 1)["repeatability_check"] is False
    assert homogeneity([[-repeat * 0.99, repeat * 0.99]] * 10, 1)["repeatability_check"] is True


def test_homogeneity_multiple_repeats() -> None:
    result = homogeneity([[float(i), float(i + 1), float(i + 2)] for i in range(10)], 5)
    assert result["f2_or_fm"] == pytest.approx(f.ppf(0.95, 9, 20) / 3)
    assert any("m>2" in warning and "专家复核" in warning for warning in result["warnings"])
    with pytest.raises(InputError):
        homogeneity([[0.0]] * 10, 1)


def test_stability_boundaries_and_independence() -> None:
    a = [[0, 0], [0, 0]]
    b = [[0.3, 0.3], [0.3, 0.3]]
    assert stability(a, b, 1)["basic_pass"] is True
    b = [[0.31, 0.31], [0.31, 0.31]]
    r = stability(a, b, 1, u1=0.01, u2=0.01)
    assert r["basic_pass"] is False and r["extended_pass"] is True
    assert stability(a, b, 1, independent=False)["basic_pass"] is None
    assert stability(a, b, None)["extended_pass"] is None
    limit = 0.3 + 2 * math.hypot(0.01, 0.01)
    for factor, expected in ((1 - 1e-8, True), (1, True), (1 + 1e-8, False)):
        followup = [[limit * factor] * 2] * 2
        assert stability(a, followup, 1, u1=0.01, u2=0.01)["extended_pass"] is expected
    with pytest.raises(InputError):
        stability(a, b, 1, u1=-1)


def test_stability_single_measurements_keep_basic_criterion() -> None:
    baseline = [[1.0], [2.0], [3.0]]
    followup = [[1.1], [2.1], [3.1]]
    result = stability(baseline, followup, 1.0)
    assert result["basic_pass"] is True
    assert result["difference"] == pytest.approx(0.1)
    assert result["sw1"] is None and result["sw2"] is None
    assert result["repeatability_exceeded"] is None
    assert sum("不可评价（单次测量）" in item for item in result["warnings"]) == 2
    mixed = stability(baseline, [[0.0, 2.0], [0.0, 2.0]], 1.0)
    assert mixed["repeatability_exceeded"] is True
    quiet = stability(baseline, [[1.0, 1.0], [1.0, 1.0]], 1.0)
    assert quiet["repeatability_exceeded"] is None


def test_stability_repeatability_review_boundaries() -> None:
    baseline = [[0.0, 0.0]] * 2
    half = 0.5 / math.sqrt(2)
    for factor, expected in ((1 - 1e-8, False), (1, False), (1 + 1e-8, True)):
        followup = [[-half * factor, half * factor]] * 2
        result = stability(baseline, followup, 1.0)
        assert result["sw1"] == 0
        assert result["sw2"] == pytest.approx(0.5 * factor)
        assert result["repeatability_exceeded"] is expected
        assert any("B.4.1.2" in warning for warning in result["warnings"]) is expected
    assert stability(baseline, baseline, None)["repeatability_exceeded"] is None
    with pytest.raises(InputError, match="溢出"):
        stability([[-1e308, 1e308]] * 2, baseline, 1.0)


def test_period_configuration_validation() -> None:
    groups = {"基线": [], "稳定期": [], "运输期": []}
    config = {
        "stability_u1": 0.01,
        "stability_u2": 0.02,
        "stability_period_options": '{"运输期":{"kind":"transport","u2":0.03}}',
    }
    settings = period_options(config, groups)
    assert settings["稳定期"] == {"kind": "storage", "u1": 0.01, "u2": 0.02}
    assert settings["运输期"] == {"kind": "transport", "u1": 0.01, "u2": 0.03}
    for raw in (
        '{"运输期":{"u2":0.1,"u2":0.2}}',
        '{"不存在":{"kind":"transport"}}',
        '{"运输期":{"kind":"unknown"}}',
        '{"运输期":{"u2":true}}',
        '{"运输期":{"u2":-1}}',
        '{"运输期":{"unexpected":1}}',
        '{"稳定期":{"u2":0.1}}',
    ):
        with pytest.raises(InputError):
            period_options({**config, "stability_period_options": raw}, groups)


def test_template_and_workflow(tmp_path: Path) -> None:
    path = tmp_path / "data.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "合成"
    book["项目信息"]["B3"] = "mg"
    book["方法配置"]["B3"] = 2
    book["方法配置"]["B21"] = "gbt28043"
    book["方法配置"]["B22"] = 0.1
    book["方法配置"]["B23"] = 0.2
    book["方法配置"]["B24"] = "gl003"
    ranges = [str(v.sqref) for v in book["方法配置"].data_validations.dataValidation]
    assert all(any(cell in r for r in ranges) for cell in ("B21", "B26", "B27"))
    for i in range(10):
        for j in range(2):
            book["均匀性"].append([str(i), str(j), i + j / 10, "mg"])
    for group, shift in (("基线", 0), ("稳定期", 0.1)):
        for i in range(3):
            for j in range(2):
                book["稳定性"].append([group, str(i), str(j), i + j / 10 + shift, "mg"])
    book.save(path)
    data = read_workbook(path)
    result = calculate(data)
    assert result["标准模式"] == "gbt28043"
    assert result["均匀性"]["reference_only"] is True
    assert result["稳定性"]["reference_only"] is True
    assert result["主判据"]["homogeneity_basic"] is False
    assert result["GB/T均匀性"]["basic_pass"] is False
    assert result["GB/T稳定性"]["稳定期"]["extended_limit"] is not None
    data["claims"] = [
        {"name": "均匀性基本限值", "value": 0.6, "digits": 3, "source": "合成", "model": "gl003"}
    ]
    rows = review(data, result)
    assert any(row["差异类型"] == "STANDARD_MODE" for row in rows)
    claimed = next(row for row in rows if row["统计量"] == "均匀性基本限值")
    assert claimed["显示一致"] and claimed["推荐一致"]
    target = tmp_path / "report.docx"
    make_report(target, data, result)
    text = "\n".join(p.text for p in Document(target).paragraphs)
    assert "GB/T 28043-2019 标准模式（主评价）" in text
    assert "GL003 计算仅为参考" in text
    assert "B.4.1.2 重复性提示：未超过" in text
    previous = data["stability"]["稳定期"]
    data["stability"]["稳定期"] = [[-2.0, 2.0]] * 3
    make_report(target, data, calculate(data))
    assert "B.4.1.2 重复性提示：超过，需审核" in "\n".join(
        p.text for p in Document(target).paragraphs
    )
    data["stability"]["稳定期"] = previous

    data["stability"]["运输期"] = [[0.1, 0.2], [0.2, 0.3], [0.3, 0.4]]
    transported = calculate(data)["GB/T稳定性"]["运输期"]
    assert transported["basic_pass"] is not None
    assert transported["extended_pass"] is None
    assert any("不复用" in warning for warning in transported["warnings"])
    data["config"]["stability_period_options"] = '{"运输期":{"kind":"transport","u2":0.03}}'
    transported = calculate(data)["GB/T稳定性"]["运输期"]
    assert transported["kind"] == "transport"
    assert transported["u2"] == 0.03 and transported["extended_pass"] is not None
    assert "B.6" in transported["reference"]
    assert any("未运输对照组" in warning for warning in transported["warnings"])
    data["claims"] = [
        {
            "name": "稳定性扩展限值",
            "value": transported["extended_limit"],
            "digits": 4,
            "source": "合成",
            "model": "gbt28043",
            "timegroup": "运输期",
        }
    ]
    row = next(r for r in review(data, calculate(data)) if r["统计量"] == "稳定性扩展限值")
    assert row["显示一致"] and row["推荐一致"] is None
    assert "非预选主判据" in row["说明"]
    data["config"]["gbt_stability_rule"] = "extended"
    row = next(r for r in review(data, calculate(data)) if r["统计量"] == "稳定性扩展限值")
    assert row["显示一致"] and row["推荐一致"]
    make_report(target, data, calculate(data))
    assert any("运输稳定性（B.6） 运输期" in p.text for p in Document(target).paragraphs)

    data["assigned_config"] = {
        "method": "known",
        "value": 10.0,
        "uncertainty": 0.2,
        "source": "合成",
        "uncertainty_source": "合成预算",
        "sigma_final": 2.0,
        "sigma_procedure": "预设",
        "hom_source": "gbt_ss",
        "hom_mapping": "sigma_prime",
        "stability_disposition": "reviewed",
        "stability_disposition_reason": "合成测试：负责人记录处置依据",
    }
    mapped = calculate(data)["指定值与不确定度"]
    assert mapped["u_hom"] == pytest.approx(result["GB/T均匀性"]["ss"])
    assert mapped["sigma_prime"] == pytest.approx(math.hypot(2, mapped["u_hom"]))
    data["assigned_config"]["hom_in_base"] = True
    assert calculate(data)["指定值与不确定度"]["status"] == "DESIGN_REVIEW"
    data["assigned_config"]["u_hom"] = 0.1
    with pytest.raises(InputError, match="不得同时"):
        calculate(data)


def test_workbook_gbt_single_stability_does_not_block_homogeneity(tmp_path: Path) -> None:
    from openpt.io.validation import inspect_input

    path = tmp_path / "single_stability.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "合成"
    book["项目信息"]["B3"] = "mg"
    book["方法配置"]["B3"] = 1.0
    book["方法配置"]["B21"] = "gbt28043"
    for uid in range(3):
        for repeat in (1, 2):
            book["均匀性"].append([uid + 1, repeat, uid + 0.01 * repeat, "mg"])
        for group, delta in (("基线", 0.0), ("稳定期", 0.1)):
            book["稳定性"].append([group, uid + 1, 1, uid + delta, "mg"])
    book.save(path)
    assert inspect_input(path) == []
    data = read_workbook(path)
    result = calculate(data)
    assert result["GB/T均匀性"]["basic_pass"] is not None
    period = result["GB/T稳定性"]["稳定期"]
    assert period["basic_pass"] is True
    assert period["sw1"] is None and period["sw2"] is None
    assert any("稳定期组内重复性不可评价（单次测量）" in w for w in period["warnings"])
    target = tmp_path / "report.docx"
    make_report(target, data, result)
    assert "稳定期组内重复性不可评价（单次测量）" in "\n".join(
        p.text for p in Document(target).paragraphs
    )


def test_preselected_primary_rule_and_no_fallback(tmp_path: Path) -> None:
    path = tmp_path / "data.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "合成"
    book["项目信息"]["B3"] = "mg"
    book.save(path)
    data = read_workbook(path)
    data["config"].update({"criterion_standard": "gbt28043", "sigma": 10})
    data["homogeneity"] = [[float(i), float(i)] for i in range(10)]
    data["stability"] = {"基线": [[0, 0], [0, 0]], "稳定期": [[3.1, 3.1], [3.1, 3.1]]}
    basic = calculate(data)
    assert basic["GB/T均匀性"]["basic_pass"] is False
    assert basic["GB/T均匀性"]["extended_pass"] is True
    assert basic["GB/T均匀性"]["conclusion"] is False
    assert basic["GB/T稳定性"]["稳定期"]["conclusion"] is False
    data["config"].update({"gbt_hom_rule": "extended", "gbt_stability_rule": "extended"})
    extended = calculate(data)
    assert extended["主判据"]["homogeneity_selected_rule"] == "extended"
    assert extended["GB/T均匀性"]["conclusion"] is True
    assert extended["GB/T稳定性"]["稳定期"]["conclusion"] is None
    target = tmp_path / "selected.docx"
    make_report(target, data, extended)
    table_text = "\n".join(
        cell.text for table in Document(target).tables for row in table.rows for cell in row.cells
    )
    assert "预选主判据" in table_text and "主结论" in table_text
    assert "未评价（未提供数据或无法计算）" in table_text
    data["config"].update({"stability_u1": 0.1, "stability_u2": 0.1})
    assert calculate(data)["GB/T稳定性"]["稳定期"]["conclusion"] is True
    data["homogeneity"] = data["homogeneity"][:6]
    assert calculate(data)["GB/T均匀性"]["conclusion"] is None
    data["config"]["gbt_hom_rule"] = "invalid"
    with pytest.raises(InputError, match="basic 或 extended"):
        calculate(data)


def test_stability_disposition_links_budget_and_blocks_pending(tmp_path: Path) -> None:
    path = tmp_path / "data.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"], book["项目信息"]["B3"] = "合成", "mg"
    book.save(path)
    data = read_workbook(path)
    data["config"].update({"criterion_standard": "gbt28043", "sigma": 1})
    data["homogeneity"] = [[0.0, 0.0]] * 10
    data["stability"] = {"基线": [[0.0, 0.0]] * 2, "稳定期": [[0.4, 0.4]] * 2}
    data["participants"] = [{"id": "L1", "value": 1.0}]
    data["assigned_config"] = a = {
        "method": "known",
        "value": 1.0,
        "uncertainty": 0.2,
        "source": "合成",
        "uncertainty_source": "合成预算",
        "sigma_final": 1.0,
        "sigma_procedure": "预设",
    }
    result = calculate(data)
    assert result["GB/T稳定性"]["稳定期"]["conclusion"] is False
    assert result["指定值与不确定度"]["status"] == "DESIGN_REVIEW"
    assert result["指定值与不确定度"]["stability_flagged_periods"] == ["稳定期"]
    assert result["参加者统计量"]["L1"]["z"]["value"] is None
    a["stability_disposition"] = "reviewed"
    with pytest.raises(InputError, match="书面依据"):
        calculate(data)
    a["stability_disposition_reason"] = "合成案例的人工批准依据"
    assert calculate(data)["指定值与不确定度"]["status"] == "OK"
    a["stability_disposition"] = "budgeted"
    with pytest.raises(InputError, match="尚未登记"):
        calculate(data)
    a.update({"u_stab": 0.1, "stab_mapping": "assigned"})
    budget = calculate(data)["指定值与不确定度"]
    assert budget["u"] == pytest.approx(math.hypot(0.2, 0.1))
    assert budget["status"] == "OK"
    a["stab_in_base"] = True
    assert calculate(data)["指定值与不确定度"]["status"] == "DESIGN_REVIEW"
    a["stab_in_base"] = False
    data["stability"]["运输期"] = [[0.5, 0.5]] * 2
    data["config"]["stability_period_options"] = '{"运输期":{"kind":"transport"}}'
    with pytest.raises(InputError, match="尚未登记"):
        calculate(data)
    a.update({"u_trans": 0.2, "trans_mapping": "assigned"})
    budget = calculate(data)["指定值与不确定度"]
    assert budget["u"] == pytest.approx(math.sqrt(0.2**2 + 0.1**2 + 0.2**2))
    assert set(budget["stability_flagged_periods"]) == {"稳定期", "运输期"}
    a.update({"u_trans": 0, "trans_mapping": "none", "trans_in_stab": True})
    budget = calculate(data)["指定值与不确定度"]
    assert budget["u"] == pytest.approx(math.hypot(0.2, 0.1))
    a.update({"u_trans": 0.2, "trans_mapping": "assigned"})
    assert calculate(data)["指定值与不确定度"]["status"] == "DESIGN_REVIEW"
    a["trans_in_stab"] = False
    target = tmp_path / "disposition.docx"
    make_report(target, data, calculate(data))
    cells = [c.text for t in Document(target).tables for r in t.rows for c in r.cells]
    assert "稳定性处置" in cells and "稳定性处置依据" in cells
    a["stability_disposition"] = "withhold"
    assert calculate(data)["指定值与不确定度"]["status"] == "DESIGN_REVIEW"
    data["stability"] = {"基线": [[0.0, 0.0]] * 2, "稳定期": [[0.0, 0.0]] * 2}
    data["config"].pop("stability_period_options")
    assert calculate(data)["指定值与不确定度"]["status"] == "DESIGN_REVIEW"
    data["config"]["gbt_stability_rule"] = "extended"
    a["stability_disposition"] = "pending"
    unevaluated = calculate(data)
    assert unevaluated["GB/T稳定性"]["稳定期"]["conclusion"] is None
    assert unevaluated["指定值与不确定度"]["status"] == "DESIGN_REVIEW"
    a["stability_disposition"] = "invalid"
    with pytest.raises(InputError, match="stability_disposition"):
        calculate(data)
    data["assigned_config"] = {}
    data["config"].update({"assigned": 1.0, "sigma_pt": 1.0})
    legacy = calculate(data)
    assert "参加者z" not in legacy and "DESIGN_REVIEW" in legacy["参加者z状态"]
    data["claims"] = [{"name": "z:L1", "value": 0.0, "digits": 2, "source": "合成"}]
    row = next(r for r in review(data, legacy) if r["统计量"] == "z:L1")
    assert row["显示一致"] is True and row["推荐一致"] is None
    assert "推荐评价暂停" in row["说明"]
    make_report(target, data, legacy)
    assert any("DESIGN_REVIEW" in p.text for p in Document(target).paragraphs)


@pytest.mark.r
@pytest.mark.parametrize("m", [2, 3])
def test_r_independent(tmp_path: Path, m: int) -> None:
    rscript = shutil.which("Rscript")
    if not rscript:
        pytest.skip("Rscript 不可用")
    x = [[float(i) + j / 10 for j in range(m)] for i in range(10)]
    y = [[1.0, 1.1], [1.2, 1.3]]
    paths = [tmp_path / "x.csv", tmp_path / "y.csv"]
    for path, values in zip(paths, (x, y), strict=True):
        path.write_text(
            "\n".join(",".join(map(str, row)) for row in values) + "\n", encoding="utf-8"
        )
    script = Path(__file__).resolve().parents[1] / "validation/r/gbt28043.R"
    process = subprocess.run(
        [rscript, str(script), str(paths[0]), str(paths[1]), "2", ".1", ".2"],
        check=True,
        capture_output=True,
        text=True,
    )
    values = {
        row["statistic"]: float(row["value"]) for row in csv.DictReader(process.stdout.splitlines())
    }
    h, s = homogeneity(x, 2), stability(x, y, 2, u1=0.1, u2=0.2)
    for rkey, key in (
        ("sx", "sx"),
        ("sw", "sw"),
        ("ss", "ss"),
        ("f1", "f1"),
        ("factor", "f2_or_fm"),
        ("c", "c"),
        ("extended_limit", "extended_limit"),
    ):
        assert values[rkey] == pytest.approx(h[key], rel=1e-10, abs=1e-12)
    assert values["difference"] == pytest.approx(s["difference"])
    assert values["sw"] == pytest.approx(s["sw1"])
    assert values["sw_followup"] == pytest.approx(s["sw2"])
    assert values["stability_limit"] == pytest.approx(s["extended_limit"])


@pytest.mark.internal
def test_internal_e2() -> None:
    root = os.environ.get("OPENPT_INTERNAL_DIR")
    if not root:
        pytest.skip("未设置内部材料目录")
    fixture = json.loads((Path(root) / "fixtures/gbt28043/e2.json").read_text(encoding="utf-8"))
    x = fixture["homogeneity"]
    sigma = sum(sum(row) for row in x) / sum(map(len, x)) * fixture["sigma_fraction_of_baseline"]
    h = homogeneity(x, sigma)
    s = stability(x, fixture["stability"], sigma)
    printed = fixture["printed"]
    for key, target in (
        ("mean", "mean"),
        ("sx", "mean_sd"),
        ("sw", "sw"),
        ("ss", "ss"),
        ("sigma", "sigma"),
        ("basic_limit", "limit"),
    ):
        assert h[key] == pytest.approx(printed[target], abs=0.0000051)
    assert h["g"] == len(x) and h["m"] == len(x[0])
    assert s["basic_limit"] == pytest.approx(printed["limit"], abs=0.0000051)
    assert s["mean2"] == pytest.approx(printed["followup_mean"], abs=0.0000051)
    assert s["difference"] == pytest.approx(printed["difference"], abs=0.0000051)
    assert h["basic_pass"] is printed["homogeneity_pass"]
    assert s["basic_pass"] is printed["stability_pass"]
