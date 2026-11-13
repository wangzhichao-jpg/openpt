# SPDX-License-Identifier: Apache-2.0
"""将随包示例放到可执行文件旁，保留内置甲醛示例的可见副本。"""

import sys
from pathlib import Path
from shutil import copy2, copytree

ROOT = Path(__file__).resolve().parent


def prepare(target: Path) -> None:
    """在已存在的程序目录中复制工作簿和四行索引。"""
    target.mkdir(parents=True, exist_ok=True)
    folder = target / "示例案例"
    copytree(ROOT / "examples", folder, dirs_exist_ok=True)
    for destination in (target / "甲醛示例.xlsx", folder / "甲醛示例.xlsx"):
        copy2(ROOT / "甲醛示例.xlsx", destination)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：python windows/prepare_examples.py 程序目录")
    prepare(Path(sys.argv[1]))
