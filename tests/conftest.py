# SPDX-License-Identifier: Apache-2.0
"""测试运行记录使用隔离目录，避免写入公开仓库。"""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """每个测试的默认运行根目录独立。"""
    monkeypatch.setenv("OPENPT_RUNS_DIR", str(tmp_path / "runs"))
