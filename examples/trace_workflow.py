# SPDX-License-Identifier: Apache-2.0
"""生成完全虚构的抽样、运行、决定、打包及重现示例。"""

import argparse
from pathlib import Path

from openpt.cli import main
from openpt.demo import _synthetic


def run(destination: Path) -> None:
    """在新目录中执行演示，不覆盖既有文件。"""
    destination.mkdir(parents=True, exist_ok=False)
    sample_dir = destination / "sampling"
    if main(
        ["sample", "--units", "20", "--pick", "10", "--seed", "42", "--output", str(sample_dir)]
    ):
        raise RuntimeError("抽样失败")
    source = destination / "synthetic.xlsx"
    _synthetic(source)
    runs = destination / "runs"
    if main(
        [
            "review",
            str(source),
            "--runs-dir",
            str(runs),
            "--sample-record",
            str(sample_dir / "sample.json"),
        ]
    ):
        raise RuntimeError("运行失败")
    run_dir = next(runs.iterdir())
    if main(
        [
            "decide",
            str(run_dir),
            "--item",
            "均匀性",
            "--decision",
            "需补充",
            "--by",
            "示例复核人",
            "--note",
            "虚构演示，非正式评价",
        ]
    ):
        raise RuntimeError("登记决定失败")
    archive = destination / "audit.zip"
    if main(["pack", str(run_dir), "-o", str(archive)]):
        raise RuntimeError("打包失败")
    if main(["verify", str(archive)]) or main(["reproduce", str(run_dir)]):
        raise RuntimeError("校验或重现失败")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="虚构可追溯工作流")
    parser.add_argument("destination", type=Path, help="新建演示目录")
    run(parser.parse_args().destination)
