# SPDX-License-Identifier: Apache-2.0
"""命令行空路径与不存在路径的防御。"""

from pathlib import Path

import pytest

from openpt.cli import main


@pytest.mark.parametrize(
    "command,extra",
    [
        ("decide", ["--item", "a", "--decision", "接受", "--by", "b"]),
        ("pack", ["--output", "out.zip"]),
        ("verify", []),
        ("reproduce", []),
        ("validate", []),
        ("run", []),
        ("review", []),
        ("review-batch", ["--output", "out.xlsx"]),
    ],
)
@pytest.mark.parametrize("empty", [True, False])
def test_bad_input_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str, extra: list[str], empty: bool
) -> None:
    path = "" if empty else str(tmp_path / "不存在")
    assert main([command, path, *extra]) == 2
    error = capsys.readouterr().err
    assert "路径" in error and ("为空" in error or "不存在" in error)
    assert "PosixPath" not in error


def test_empty_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["template", ""]) == 2
    assert "路径不能为空" in capsys.readouterr().err
