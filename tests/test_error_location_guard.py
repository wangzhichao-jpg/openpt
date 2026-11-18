# SPDX-License-Identifier: Apache-2.0
"""输入错误必须可定位或记录有根据的豁免。"""

import ast
import io
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ("src/openpt/cli.py", "src/openpt/core/assigned.py", "src/openpt/config/rules.py")


def test_input_error_has_location_or_exemption() -> None:
    failures = []
    for name in FILES:
        source = (ROOT / name).read_text(encoding="utf-8")
        comments = {
            token.start[0]: token.string
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
            if token.type == tokenize.COMMENT
        }
        for node in ast.walk(ast.parse(source, filename=name)):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            function = node.exc.func
            if not isinstance(function, ast.Name) or function.id != "InputError":
                continue
            if {keyword.arg for keyword in node.exc.keywords} & {"field", "fields", "sheet"}:
                continue
            candidates = (comments.get(node.lineno, ""), comments.get(node.lineno - 1, ""))
            if not any(
                comment.startswith("# 定位豁免：") and comment.split("：", 1)[1].strip()
                for comment in candidates
            ):
                failures.append(f"{name}:{node.lineno}")
    assert not failures, "缺少定位或豁免：\n" + "\n".join(failures)
