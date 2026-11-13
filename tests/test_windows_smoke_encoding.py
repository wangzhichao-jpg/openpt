# SPDX-License-Identifier: Apache-2.0
"""Windows 冒烟检查器在 CP1252 输出环境下保留两种案例检查。"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from openpt.windows_app import example_path, run_workbook, summarize

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("transfer", [False, True])
def test_smoke_checker_cp1252(tmp_path: Path, transfer: bool) -> None:
    source = ROOT / "windows/examples/数字多用表.xlsx" if transfer else example_path()
    directory, data, result = run_workbook(source, tmp_path)
    (tmp_path / "gui-smoke.txt").write_text(
        summarize(data, result) + "\n" + str(directory), encoding="utf-8"
    )
    args = [sys.executable, str(ROOT / "windows/check_smoke.py"), str(tmp_path)]
    if transfer:
        args.append("传递")
    process = subprocess.run(
        args,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        capture_output=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr.decode("cp1252", errors="replace")
    expected = b"Transfer GUI smoke checks passed." if transfer else b"GUI smoke checks passed."
    assert expected in process.stdout
