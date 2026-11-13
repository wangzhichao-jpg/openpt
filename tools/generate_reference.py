# SPDX-License-Identifier: Apache-2.0
"""从代码枚举生成手册参考清单；--check 检测差异。"""

import argparse
from pathlib import Path

from openpt.config.catalog import markdown

ROOT = Path(__file__).resolve().parents[1]
BEGIN = "<!-- OPENPT-CATALOG-BEGIN -->"
END = "<!-- OPENPT-CATALOG-END -->"


def updated(text: str) -> str:
    """替换受管理区域；不存在时追加到手册。"""
    block = BEGIN + "\n" + markdown() + "\n" + END
    if BEGIN not in text and END not in text:
        return text.rstrip() + "\n\n## 参数与复核参考清单\n\n" + block + "\n"
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ValueError("手册参考清单标记缺失或重复")
    before, rest = text.split(BEGIN, 1)
    _, after = rest.split(END, 1)
    return before + block + after


def main() -> int:
    parser = argparse.ArgumentParser(description="生成参数参考清单")
    parser.add_argument("--check", action="store_true", help="仅检查是否需要更新")
    args = parser.parse_args()
    path = ROOT / "docs/开发者命令行参考.md"
    original = path.read_text(encoding="utf-8")
    result = updated(original)
    if args.check:
        if original != result:
            print("手册参考清单与代码不一致，请运行 tools/generate_reference.py")
            return 1
        return 0
    path.write_text(result, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
