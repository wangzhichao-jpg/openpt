# SPDX-License-Identifier: Apache-2.0
import json
import math
from pathlib import Path

import pytest
from openpyxl import load_workbook

from openpt.cli import main
from openpt.core.homogeneity import analyze as hom
from openpt.core.robust import algorithm_a
from openpt.core.stability import analyze as stab
from openpt.core.zscore import zscore
from openpt.io.excel import read_workbook, template

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = json.loads((ROOT / "tests/fixtures_public/gl003_cases.json").read_text())


def test_u1_u2():
    # GL003 附录 A.1 表1、表2和 A.2 表3、表4。
    a = hom(PUBLIC["A1"]["data"])
    assert (
        round(a["F"], 2) == 1.17 and round(a["F_critical"], 2) == 3.02 and a["conclusion"] is True
    )
    a = hom(PUBLIC["A2"]["data"], 1.1)
    assert round(a["F"], 2) == 3.78 and round(a["F_critical"], 2) == 2.72
    assert (
        round(a["Ss"], 3) == 0.292
        and a["threshold"] == pytest.approx(0.330)
        and a["Ss_pass"]
        and not a["conclusion"]
    )
    assert not hom(PUBLIC["A2"]["data"], 1.1, strict=True)["conclusion"]


def test_u3_u4_u5_u6():
    # 人工构造：10×[9,11]，组均值一致；10×[10,10] 全部相等。
    a = hom([[9, 11]] * 10)
    assert (
        a["F"] == 0
        and a["variance_raw"] == -1
        and a["Ss"] == 0
        and a["status"] == "OK"
        and a["warnings"]
    )
    a = hom([[10, 10]] * 10)
    assert a["status"] == "INDETERMINATE" and a["F"] is None and a["p"] is None
    assert hom(PUBLIC["A1"]["data"])["Ss_status"] == "NOT_EVALUATED"
    assert hom(PUBLIC["A1"]["data"][:8])["design_warnings"]
    assert hom([[10, 10]] * 8)["status"] == "INDETERMINATE"
    assert hom([[10, 10]] * 8)["design_warnings"]
    assert hom(PUBLIC["A1"]["data"], strict=True)["conclusion"] is None
    assert hom(PUBLIC["A2"]["data"], strict=True)["conclusion"] is False


def test_u10():
    # GL002 附录 A.2；对称合成数据的稳健均值解析为2。
    values = [1, 2, 3, 4, 0]
    a = algorithm_a(values, tolerance=1e-12)
    assert a["x"] == pytest.approx(2)
    try:
        from pt13528.robust import algorithm_a as external_algorithm_a
    except ImportError:
        external_algorithm_a = None
    if external_algorithm_a:
        ext = external_algorithm_a(values, tol=1e-13)
        assert a["x"] == pytest.approx(ext.location, abs=1e-10) and a["s"] == pytest.approx(
            ext.scale, abs=1e-10
        )
    assert a["u_x"] == pytest.approx(1.25 * a["s"] / math.sqrt(5))
    assert algorithm_a(values, simplified=True)["iterations"] == 0
    assert algorithm_a(values, max_iterations=1)["status"] == "NOT_CONVERGED"


def fill(path, data):
    template(path)
    w = load_workbook(path)
    w["项目信息"]["B2"] = "GL003 A.1"
    w["项目信息"]["B3"] = "mg/kg"
    for i, row in enumerate(data, 1):
        for j, v in enumerate(row, 1):
            w["均匀性"].append([str(i), str(j), v, "mg/kg"])
    w.save(path)


def test_u13_and_u4_docx(tmp_path):
    # GL003 A.1 表1、2；另用人工构造零方差输入。
    x = tmp_path / "in.xlsx"
    fill(x, PUBLIC["A1"]["data"])
    assert (
        main(
            ["run", str(x), "--docx", str(tmp_path / "r.docx"), "--json", str(tmp_path / "r.json")]
        )
        == 0
    )
    assert round(json.loads((tmp_path / "r.json").read_text())["均匀性"]["F"], 2) == 1.17
    fill(x, [[10, 10]] * 10)
    assert (
        main(
            [
                "run",
                str(x),
                "--docx",
                str(tmp_path / "zero.docx"),
                "--json",
                str(tmp_path / "zero.json"),
            ]
        )
        == 0
    )
    assert json.loads((tmp_path / "zero.json").read_text())["均匀性"]["F"] is None


def test_input_validation(tmp_path):
    # GL003 4.1 所述重复取样以及固定模板人工错误。
    x = tmp_path / "in.xlsx"
    fill(x, PUBLIC["A1"]["data"])
    w = load_workbook(x)
    w["均匀性"]["D2"] = "bad"
    w.save(x)
    with pytest.raises(ValueError, match="单位"):
        read_workbook(x)
    w["均匀性"]["D2"] = "mg/kg"
    w["均匀性"]["C2"] = "=1+1"
    w.save(x)
    with pytest.raises(ValueError, match="公式"):
        read_workbook(x)
    with pytest.raises(ValueError):
        hom([[1], [2, 3]])
    with pytest.raises(ValueError):
        hom([[1, 2], [2, 3]], -1)
    with pytest.raises(ValueError):
        algorithm_a([1])
    with pytest.raises(ValueError):
        zscore(1, 1, 0)


def test_z_and_stability():
    # GL002 4.5.1.1 边界；GL003 5.2.1 人工构造样本。
    assert (
        zscore(2, 0, 1)["classification"] == "满意"
        and zscore(2.5, 0, 1)["classification"] == "可疑"
        and zscore(3, 0, 1)["classification"] == "不满意"
    )
    a = stab(None, [[1, 2], [2, 3], [3, 4]], sigma=1, method="one_sample", reference=2)
    assert a["df"] == 2 and a["status"] == "OK" and a["design_warnings"]
    assert stab([[1, 1], [1, 1]], [[1, 1], [1, 1]])["status"] == "INDETERMINATE"
    with pytest.raises(ValueError):
        stab(None, [[1], [2]], method="one_sample")
