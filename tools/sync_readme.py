# SPDX-License-Identifier: Apache-2.0
"""由 README.en.md 生成 .github/README.md，使 GitHub 首页默认显示英文。

GitHub 优先显示 .github/README.md；Gitee 显示根目录 README.md（中文）。
.github/README.md 中的相对链接以 .github/ 为基准，因此统一加 ../ 前缀。
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "README.en.md"
TARGET = ROOT / ".github" / "README.md"
HEADER = "<!-- 由 tools/sync_readme.py 从 README.en.md 生成，请勿直接修改。 -->\n"
LINK = re.compile(r"\]\((?!https?://|mailto:|#|/)([^)\s]+)\)")


def render(text: str) -> str:
    """为相对链接加 ../ 前缀并加生成说明。"""
    return HEADER + LINK.sub(lambda m: f"](../{m.group(1)})", text)


def main() -> int:
    expected = render(SOURCE.read_text(encoding="utf-8"))
    if "--check" in sys.argv[1:]:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != expected:
            print(".github/README.md 与 README.en.md 不一致；请运行 python tools/sync_readme.py")
            return 1
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
