# SPDX-License-Identifier: Apache-2.0
"""防止文本 I/O 依赖 Windows 默认编码。"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BINARY_MODULES = {"tarfile", "zipfile", "gzip", "bz2", "lzma"}


def _missing_encoding(source: str) -> list[int]:
    """检查文本 open/read_text/write_text；二进制和压缩包 API 除外。"""
    missing = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else func.attr
            if isinstance(func, ast.Attribute)
            else ""
        )
        if name not in {"open", "read_text", "write_text"}:
            continue
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in BINARY_MODULES
        ):
            continue
        keywords = {item.arg: item.value for item in node.keywords}
        if "encoding" in keywords and not (
            isinstance(keywords["encoding"], ast.Constant) and keywords["encoding"].value is None
        ):
            continue
        mode = keywords.get("mode")
        if mode is None and name == "open":
            index = 0 if isinstance(func, ast.Attribute) else 1
            mode = node.args[index] if len(node.args) > index else None
        if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" in mode.value:
            continue
        missing.append(node.lineno)
    return missing


def test_text_io_explicit_encoding() -> None:
    """检查 src、tests、tools 下所有 Python 文件。"""
    violations = []
    for directory in ("src", "tests", "tools"):
        for path in (ROOT / directory).rglob("*.py"):
            for line in _missing_encoding(path.read_text(encoding="utf-8")):
                violations.append(f"{path.relative_to(ROOT)}:{line}")
    assert not violations, "文本 I/O 缺少 encoding：" + ", ".join(violations)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("open('x')", [1]),
        ("p.open('w')", [1]),
        ("p.read_text()", [1]),
        ("p.write_text('字')", [1]),
        ("open('x', 'rb')", []),
        ("p.open(mode='wb')", []),
        ("p.read_text(encoding='utf-8')", []),
        ("tarfile.open('x', 'r:gz')", []),
        ("open('x', encoding=None)", [1]),
    ],
)
def test_encoding_guard(source: str, expected: list[int]) -> None:
    """确认检查器对文本、二进制及压缩包分别处理。"""
    assert _missing_encoding(source) == expected
