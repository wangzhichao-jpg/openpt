# SPDX-License-Identifier: Apache-2.0
"""已知 R 差异不能成为无条件豁免。"""

import importlib
import json
import sys
from pathlib import Path

import pytest

VALIDATION = Path(__file__).resolve().parents[1] / "validation"
sys.path.insert(0, str(VALIDATION))
crosscheck = importlib.import_module("run_r_crosscheck")
KNOWN = json.loads((VALIDATION / "known_differences.json").read_text(encoding="utf-8"))


def test_zero_residual_boundary_and_identity() -> None:
    row = {"case": "负方差", "statistic": "F", "openpt": 0.0, "r": 1e-31}
    assert crosscheck.known_difference(row, KNOWN)
    for change in (
        {"case": "其他"},
        {"statistic": "p"},
        {"openpt": 1e-20},
        {"r": 1e-12},
        {"r": float("nan")},
    ):
        assert crosscheck.known_difference({**row, **change}, KNOWN) is None


def test_degenerate_requires_both_small_variances_and_indeterminate() -> None:
    row = {
        "case": "全部相同",
        "statistic": "F,p",
        "openpt_status": "INDETERMINATE",
        "openpt_F": None,
        "openpt_p": None,
        "r_values": {"MS_between": 1e-29, "MS_within": 1e-30, "F": 1.0, "p": 0.5},
    }
    assert crosscheck.known_difference(row, KNOWN)
    assert crosscheck.known_difference({**row, "openpt_F": 0.0}, KNOWN) is None
    assert crosscheck.known_difference({**row, "openpt_status": "OK"}, KNOWN) is None
    for key in ("MS_between", "MS_within"):
        assert (
            crosscheck.known_difference({**row, "r_values": {**row["r_values"], key: 1e-12}}, KNOWN)
            is None
        )
    assert (
        crosscheck.known_difference({**row, "r_values": {**row["r_values"], "p": 1.1}}, KNOWN)
        is None
    )


def test_random_case_also_requires_input_fingerprint() -> None:
    entry = next(item for item in KNOWN if item["case"].startswith("case_"))
    row = {
        "case": entry["case"],
        "statistic": entry["statistic"],
        "openpt": 0.0,
        "r": 1e-31,
        "input_sha256": entry["input_sha256"],
    }
    assert crosscheck.known_difference(row, KNOWN)
    assert crosscheck.known_difference({**row, "input_sha256": "different"}, KNOWN) is None
    assert (
        crosscheck.known_difference(
            {key: v for key, v in row.items() if key != "input_sha256"}, KNOWN
        )
        is None
    )


@pytest.mark.parametrize("condition", ["unknown", "", None])
def test_unknown_conditions_fail_closed(condition: str | None) -> None:
    row = {"case": "负方差", "statistic": "F", "openpt": 0.0, "r": 1e-31}
    assert (
        crosscheck.known_difference(
            row, [{"case": "负方差", "statistic": "F", "reason": "理由", "condition": condition}]
        )
        is None
    )
