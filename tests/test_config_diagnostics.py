# SPDX-License-Identifier: Apache-2.0
"""配置预检及未评价提示的合成示例。"""

from pathlib import Path

from openpyxl import load_workbook

from openpt.io.validation import inspect_input
from openpt.windows_app import run_workbook, summarize

EXAMPLE = Path(__file__).resolve().parents[1] / "windows/examples/GB-T合成检测.xlsx"


def _set(book: object, sheet: str, field: str, value: object) -> None:
    for row in book[sheet].iter_rows(min_row=2):  # type: ignore[index]
        key = str(row[0].value)
        if key == field or key.endswith(f"（{field}）"):
            row[1].value = value
            return
    raise AssertionError(field)


def test_preflight_collects_multiple_configuration_errors(tmp_path: Path) -> None:
    book = load_workbook(EXAMPLE)
    for field, value in (("source", None), ("uncertainty_source", None), ("hom_mapping", "none")):
        _set(book, "指定值与不确定度", field, value)
    path = tmp_path / "invalid.xlsx"
    book.save(path)
    issues = inspect_input(path)
    messages = "\n".join(f"{i.sheet} {i.cell} {i.message}" for i in issues)
    assert "source" in messages and "uncertainty_source" in messages
    assert "hom_mapping" in messages and "hom_source=gbt_ss" in messages
    assert all(i.cell.startswith("B") for i in issues if i.sheet == "指定值与不确定度")


def test_missing_criterion_and_pending_are_explained(tmp_path: Path) -> None:
    book = load_workbook(EXAMPLE)
    _set(book, "方法配置", "sigma", None)
    path = tmp_path / "missing.xlsx"
    book.save(path)
    _, data, result = run_workbook(path, tmp_path / "runs")
    text = str(result["诊断提示"])
    assert "sigma_final" in text and "不作为均匀性" in text
    assert "pending" in text and "稳定期" in text
    assert summarize(data, result).startswith("【诊断提示】")


def test_synthetic_gbt_example_scores(tmp_path: Path) -> None:
    _, _, result = run_workbook(EXAMPLE, tmp_path / "runs")
    assert result["指定值与不确定度"]["status"] == "OK"
    assert all(row["z"]["value"] is not None for row in result["参加者统计量"].values())
