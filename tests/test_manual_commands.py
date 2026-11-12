# SPDX-License-Identifier: Apache-2.0
"""逐条执行手册命令，采用公开合成数据与临时目录。"""

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def test_manual_commands(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "docs/使用手册.md").read_text(encoding="utf-8")
    commands = [line for line in text.splitlines() if line.startswith("openpt ")]
    assert len(commands) == 12
    shutil.copyfile(root / "examples/GL003_A1.xlsx", tmp_path / "input.xlsx")
    (tmp_path / "examples").mkdir()
    for name in ("trend_synthetic.xlsx", "transfer_synthetic.xlsx"):
        shutil.copyfile(root / "examples" / name, tmp_path / "examples" / name)
    env = dict(os.environ)
    for line in commands:
        args = shlex.split(line)
        if "$RUN" in args:
            runs = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()]
            assert len(runs) == 1
            args = [str(runs[0]) if item == "$RUN" else item for item in args]
        result = subprocess.run(
            [sys.executable, "-m", "openpt", *args[1:]],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0, (line, result.stdout, result.stderr)
