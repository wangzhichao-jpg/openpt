# SPDX-License-Identifier: Apache-2.0
"""同步工作簿与使用手册的常见场景说明。"""

import argparse
from pathlib import Path

from openpt.config.workbook_guidance import scenario_markdown

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs/使用手册.md"
BEGIN = "<!-- OPENPT-SCENARIOS-BEGIN -->"
END = "<!-- OPENPT-SCENARIOS-END -->"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    original = TARGET.read_text(encoding="utf-8")
    block = BEGIN + "\n" + scenario_markdown() + "\n" + END
    if BEGIN in original and END in original:
        before, rest = original.split(BEGIN, 1)
        _, after = rest.split(END, 1)
        result = before + block + after
    else:
        anchor = "### 参加者结果统计与多被测量"
        result = original.replace(anchor, "### 常见场景怎么填\n\n" + block + "\n\n" + anchor, 1)
    if args.check:
        if result != original:
            print("常见场景说明需要同步")
            return 1
    else:
        TARGET.write_text(result, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
