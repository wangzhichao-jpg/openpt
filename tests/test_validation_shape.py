# SPDX-License-Identifier: Apache-2.0
"""导入与只读检查共享最小样本和重复数规则。"""

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given, settings
from hypothesis import strategies as st
from openpyxl import load_workbook

from openpt.cli import calculate, main
from openpt.io.excel import read_workbook, template
from openpt.io.validation import _check_rows, inspect_input


def test_stability_sample_count_and_balance() -> None:
    rows = [
        ["时间组", "单元编号", "重复编号", "值", "单位"],
        ["一", "A", 1, 1.0, "mg"],
        ["二", "B", 1, 1.0, "mg"],
        ["二", "B", 2, 1.0, "mg"],
        ["二", "C", 1, 1.0, "mg"],
    ]
    issues = _check_rows("稳定性", rows, [], {})
    assert any(i.category == "INSUFFICIENT_SAMPLES" and i.cell == "D2" for i in issues)
    assert any(i.category == "UNBALANCED_REPEATS" and i.cell == "D3" for i in issues)


@given(
    st.lists(
        st.lists(st.one_of(st.none(), st.integers(-20, 20)), min_size=1, max_size=3),
        min_size=1,
        max_size=4,
    )
)
@settings(max_examples=25, deadline=None)
def test_random_homogeneity_workbooks_validate_before_calculate(
    groups: list[list[int | None]],
) -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "input.xlsx"
        template(path)
        book = load_workbook(path)
        book["项目信息"]["B2"] = "测试"
        book["项目信息"]["B3"] = "mg"
        for unit, values in enumerate(groups):
            for repeat, value in enumerate(values):
                book["均匀性"].append([unit + 1, repeat + 1, value, "mg"])
        book.save(path)
        book.close()
        if not inspect_input(path):
            calculate(read_workbook(path))


def test_shared_missing_group_and_gbt_balance(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "测试"
    book["项目信息"]["B3"] = "mg"
    for uid in (1, 2):
        for repeat in (1, 2):
            book["均匀性"].append([uid, repeat, float(uid), "mg"])
            book["稳定性"].append(["稳定期", uid, repeat, float(uid), "mg"])
    book.save(path)
    assert any(issue.category == "MISSING_GROUP" for issue in inspect_input(path))
    assert main(["run", str(path), "--runs-dir", str(tmp_path / "runs")]) == 2
    book["方法配置"].append(["stability_method", "one_sample"])
    book.save(path)
    assert any(issue.category == "MISSING_CONFIG" for issue in inspect_input(path))
    book["稳定性"].delete_rows(2, book["稳定性"].max_row)
    book["方法配置"].append(["criterion_standard", "gbt28043"])
    book["均匀性"].append([1, 3, 1.1, "mg"])
    book.save(path)
    assert any(issue.category == "UNBALANCED_REPEATS" for issue in inspect_input(path))


def test_optional_sheets_can_be_absent_and_metadata_is_checked(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "测试"
    book["项目信息"]["B3"] = "mg"
    for uid in (1, 2):
        for repeat in (1, 2):
            book["均匀性"].append([uid, repeat, float(uid + repeat), "mg"])
    for name in list(book.sheetnames):
        if name not in ("项目信息", "均匀性"):
            del book[name]
    book.save(path)
    assert not inspect_input(path)
    assert main(["run", str(path), "--runs-dir", str(tmp_path / "runs")]) == 0
    book["项目信息"]["B3"] = None
    book.save(path)
    assert any(
        i.category == "MISSING" and i.sheet == "项目信息" and i.cell == "B3"
        for i in inspect_input(path)
    )


def test_optional_participant_cells_are_checked(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "测试"
    book["项目信息"]["B3"] = "mg"
    book["参加者结果"].append(["P1", 1.0, "mg", "错误", "=1+1", 2])
    book.save(path)
    issues = inspect_input(path)
    assert any(
        i.category == "NON_NUMERIC" and i.sheet == "参加者结果" and i.cell == "D2" for i in issues
    )
    assert any(
        i.category == "FORMULA_NO_CACHE" and i.sheet == "参加者结果" and i.cell == "E2"
        for i in issues
    )


def test_claim_precision_is_validated(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "测试"
    book["项目信息"]["B3"] = "mg"
    for uid in (1, 2):
        for repeat in (1, 2):
            book["均匀性"].append([uid, repeat, uid + repeat / 10, "mg"])
    book["报告声称值"].append(["F", 1.0, 1.5, "报告"])
    book.save(path)
    assert any(i.category == "INVALID_PRECISION" and i.cell == "C2" for i in inspect_input(path))
    book["报告声称值"]["C2"] = None
    book.save(path)
    assert any(
        i.category == "MISSING" and i.sheet == "报告声称值" and i.cell == "C2"
        for i in inspect_input(path)
    )


def test_algorithm_s_shape_and_value_issues(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    template(path)
    book = load_workbook(path)
    book["项目信息"]["B2"] = "测试"
    book["项目信息"]["B3"] = "mg"
    book["算法S"].append([-1, 12])
    book.save(path)
    found = {
        (issue.category, issue.cell) for issue in inspect_input(path) if issue.sheet == "算法S"
    }
    assert ("INVALID_VALUE", "A2") in found
    assert ("INVALID_DF", "B2") in found
    assert ("INSUFFICIENT_SAMPLES", "A2") in found
    book["算法S"]["A2"] = 1
    book["算法S"]["B2"] = 2
    book["算法S"].append([1, 3])
    book.save(path)
    assert any(
        issue.category == "INVALID_DF" and issue.cell == "B3" for issue in inspect_input(path)
    )


_GROUPS = st.lists(
    st.lists(st.one_of(st.none(), st.integers(-10, 10)), min_size=1, max_size=3),
    min_size=0,
    max_size=4,
)


@given(
    homogeneity=_GROUPS,
    baseline=_GROUPS,
    followup=_GROUPS,
    method=st.sampled_from(["one_sample", "two_sample", "mean_difference"]),
    standard=st.sampled_from(["gl003", "gbt28043"]),
    reference=st.one_of(st.none(), st.just(1.0)),
)
@settings(max_examples=45, deadline=None)
def test_random_workbooks_validate_before_run(
    homogeneity: list[list[int | None]],
    baseline: list[list[int | None]],
    followup: list[list[int | None]],
    method: str,
    standard: str,
    reference: float | None,
) -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "input.xlsx"
        template(path)
        book = load_workbook(path)
        book["项目信息"]["B2"] = "测试"
        book["项目信息"]["B3"] = "mg"
        book["方法配置"].append(["stability_method", method])
        book["方法配置"].append(["criterion_standard", standard])
        if reference is not None:
            book["方法配置"].append(["reference", reference])
        for unit, values in enumerate(homogeneity, 1):
            for repeat, value in enumerate(values, 1):
                book["均匀性"].append([unit, repeat, value, "mg"])
        for name, groups in (("基线", baseline), ("稳定期", followup)):
            for unit, values in enumerate(groups, 1):
                for repeat, value in enumerate(values, 1):
                    book["稳定性"].append([name, unit, repeat, value, "mg"])
        book.save(path)
        book.close()
        if not inspect_input(path):
            assert main(["run", str(path), "--runs-dir", str(Path(directory) / "runs")]) == 0
