# SPDX-License-Identifier: Apache-2.0
"""用实际工作簿数据触发计算阶段的表名定位。"""

from pathlib import Path

import pytest
from openpyxl import load_workbook

from openpt.cli import calculate
from openpt.errors import InputError
from openpt.io.excel import read_workbook
from openpt.review.compare import review

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "windows/examples/GB-T合成检测.xlsx"


def _calculate_after_read(path: Path, sheet: str) -> None:
    # 先完成读取，确保异常来自计算而非 Excel 输入解析。
    data = read_workbook(path)
    with pytest.raises(InputError, match=f"『{sheet}』"):
        calculate(data)


def test_homogeneity_single_unit_real_data(tmp_path: Path) -> None:
    book = load_workbook(BASE)
    ws = book["均匀性"]
    ws.delete_rows(4, ws.max_row - 3)
    path = tmp_path / "hom.xlsx"
    book.save(path)
    _calculate_after_read(path, "均匀性")


def test_stability_single_unit_real_data(tmp_path: Path) -> None:
    book = load_workbook(BASE)
    ws = book["稳定性"]
    for row in range(ws.max_row, 1, -1):
        if ws.cell(row, 1).value == "稳定期" and ws.cell(row, 2).value != "1":
            ws.delete_rows(row)
    path = tmp_path / "stability.xlsx"
    book.save(path)
    _calculate_after_read(path, "稳定性")


def test_trend_insufficient_points_real_data(tmp_path: Path) -> None:
    book = load_workbook(ROOT / "examples/synthetic/trend_synthetic.xlsx")
    ws = book["趋势稳定性"]
    ws.delete_rows(4, ws.max_row - 3)
    path = tmp_path / "trend.xlsx"
    book.save(path)
    _calculate_after_read(path, "趋势稳定性")


def test_algorithm_s_one_observation_real_data(tmp_path: Path) -> None:
    book = load_workbook(BASE)
    book["算法S"].append([1, 2])
    path = tmp_path / "algorithm-s.xlsx"
    book.save(path)
    _calculate_after_read(path, "算法S")


def test_participant_consensus_one_result_real_data(tmp_path: Path) -> None:
    book = load_workbook(BASE)
    ws = book["参加者结果"]
    ws.delete_rows(3, ws.max_row - 2)
    path = tmp_path / "participant.xlsx"
    book.save(path)
    _calculate_after_read(path, "参加者结果")


def test_review_duplicate_trend_claim_real_data(tmp_path: Path) -> None:
    book = load_workbook(ROOT / "examples/synthetic/trend_synthetic.xlsx")
    ws = book["报告声称值"]
    ws.append(["b1", 0.6, 1, "合成报告", None, "短期"])
    ws.append(["b1", 0.6, 1, "合成报告", None, "短期"])
    path = tmp_path / "claims.xlsx"
    book.save(path)
    data = read_workbook(path)
    result = calculate(data, review_mode=True)
    with pytest.raises(InputError, match="『报告声称值』"):
        review(data, result)


def test_measurand_config_duplicate_is_located_during_read(tmp_path: Path) -> None:
    book = load_workbook(ROOT / "examples/synthetic/multi.xlsx")
    book["被测量配置"].append(["甲", "sigma", 1])
    path = tmp_path / "measurands.xlsx"
    book.save(path)
    with pytest.raises(InputError, match="被测量配置!"):
        read_workbook(path)


def test_transfer_too_few_measurements_real_data(tmp_path: Path) -> None:
    book = load_workbook(ROOT / "examples/synthetic/transfer_synthetic.xlsx")
    ws = book["传递标准复测"]
    ws.delete_rows(3, ws.max_row - 2)
    # 将保留记录设为窗口内，以便到达最少测量数检查。
    ws["E2"] = "传递中"
    path = tmp_path / "transfer-observations.xlsx"
    book.save(path)
    _calculate_after_read(path, "传递标准复测")


def test_transfer_invalid_limit_real_data(tmp_path: Path) -> None:
    book = load_workbook(ROOT / "examples/synthetic/transfer_synthetic.xlsx")
    book["传递标准配置"]["E2"] = '[{"kind":"fixed","value":-1}]'
    path = tmp_path / "transfer.xlsx"
    book.save(path)
    _calculate_after_read(path, "传递标准配置")
