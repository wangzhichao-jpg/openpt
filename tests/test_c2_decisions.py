# SPDX-License-Identifier: Apache-2.0
"""人工决定必须绑定实际结果，除非显式登记自定义条目。"""

import json
from pathlib import Path

import pytest

from openpt.cli import main
from openpt.demo import _a1
from openpt.runs import verify_directory


def test_decision_items(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """错误条目不改快照；显式允许时记录自定义标识。"""
    source = tmp_path / "input.xlsx"
    _a1(source)
    runs = tmp_path / "runs"
    assert main(["run", str(source), "--runs-dir", str(runs)]) == 0
    root = next(runs.iterdir())
    args = ["decide", str(root), "--item", "均匀性误拼", "--decision", "接受", "--by", "复核人"]
    assert main(args) == 2
    assert "可用条目：均匀性" in capsys.readouterr().err
    # 拒绝必须在变更审计内容之前发生。
    assert not (root / "decisions.jsonl").exists()
    assert verify_directory(root) == []
    assert main([*args, "--allow-new-item"]) == 0
    record = json.loads((root / "decisions.jsonl").read_text(encoding="utf-8"))
    assert record["item"] == "均匀性误拼"
    assert record["custom_item"] is True
    assert verify_directory(root) == []
