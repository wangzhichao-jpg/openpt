# SPDX-License-Identifier: Apache-2.0
"""审计包的清单与 ZIP 完整性检查；不执行其中的代码。"""

import hashlib
import json
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from .errors import InputError

MANIFEST = "manifest.json"
MAX_FILE_SIZE = 256 * 1024 * 1024
MAX_TOTAL_SIZE = 1024 * 1024 * 1024


def _safe_name(name: str) -> bool:
    """拒绝绝对路径、平台歧义路径及点路径，防止 ZIP 路径穿越。"""
    parts = name.split("/")
    return (
        bool(name)
        and "\\" not in name
        and ":" not in name
        and "\x00" not in name
        and not name.startswith("/")
        and all(part not in ("", ".", "..") for part in parts)
        and str(PurePosixPath(name)) == name
    )


def _manifest(raw: bytes) -> dict[str, str]:
    """读取清单中的相对文件名和 SHA-256，不信任清单内容。"""
    try:
        data: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise InputError("manifest.json 无法解析") from exc
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise InputError("manifest.json 缺少 files 对象")
    files = data["files"]
    for name, digest in files.items():
        if (
            not isinstance(name, str)
            or not _safe_name(name)
            or name == MANIFEST
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise InputError("manifest.json 含无效文件名或哈希")
    return dict(files)


def _digest(stream: Any) -> str:
    """分块计算 SHA-256。"""
    h = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        h.update(chunk)
    return h.hexdigest()


def verify_zip(path: str | Path) -> list[str]:
    """验证清单覆盖的全部文件，返回差异列表；绝不解压或执行。"""
    with ZipFile(path, "r") as zipfile:
        entries = zipfile.infolist()
        names = [item.filename for item in entries]
        if len(names) != len(set(names)):
            raise InputError("审计包包含重复路径")
        total = 0
        for item in entries:
            mode = item.external_attr >> 16
            if not _safe_name(item.filename) or item.is_dir() or stat.S_ISLNK(mode):
                raise InputError(f"审计包包含不安全路径或链接：{item.filename!r}")
            total += item.file_size
            if item.file_size > MAX_FILE_SIZE or total > MAX_TOTAL_SIZE:
                raise InputError("审计包解压大小超限")
        if MANIFEST not in names:
            raise InputError("审计包缺少 manifest.json")
        if zipfile.getinfo(MANIFEST).file_size > 4 * 1024 * 1024:
            raise InputError("manifest.json 过大")
        files = _manifest(zipfile.read(MANIFEST))
        expected = set(files) | {MANIFEST}
        actual = set(names)
        differences = [f"缺少文件：{name}" for name in sorted(expected - actual)]
        differences.extend(f"未列入清单：{name}" for name in sorted(actual - expected))
        for name in sorted(set(files) & actual):
            with zipfile.open(name) as stream:
                if _digest(stream) != files[name]:
                    differences.append(f"哈希不一致：{name}")
        return differences


def pack_directory(directory: str | Path, output: str | Path) -> None:
    """将完整清单覆盖的运行目录打包；不覆盖文件且不修改输入。"""
    root = Path(directory)
    target = Path(output)
    if not root.is_dir() or root.is_symlink():
        raise InputError("运行目录不存在或为符号链接")
    if target.resolve().is_relative_to(root.resolve()):
        raise InputError("审计包不得写入运行目录")
    files = _manifest((root / MANIFEST).read_bytes())
    paths: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise InputError("运行目录不得包含符号链接")
        if path.is_file():
            name = path.relative_to(root).as_posix()
            if not _safe_name(name):
                raise InputError("运行目录含不安全文件名")
            paths[name] = path
    if set(paths) != set(files) | {MANIFEST}:
        raise InputError("运行目录的文件与清单不一致")
    sizes = [path.stat().st_size for path in paths.values()]
    if any(size > MAX_FILE_SIZE for size in sizes) or sum(sizes) > MAX_TOTAL_SIZE:
        raise InputError("运行目录文件大小超限")
    for name, digest in files.items():
        with paths[name].open("rb") as stream:
            if _digest(stream) != digest:
                raise InputError(f"哈希不一致：{name}")
    # x 模式原子拒绝覆盖；如写入失败则删除不完整的新文件。
    try:
        with target.open("xb") as stream:
            try:
                with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
                    for name in sorted(paths):
                        archive.write(paths[name], arcname=name)
                stream.flush()
                differences = verify_zip(target)
                if differences:
                    raise InputError("打包期间文件变化：" + "；".join(differences))
            except BaseException:
                stream.close()
                target.unlink(missing_ok=True)
                raise
    except FileExistsError:
        raise InputError("审计包输出已存在，拒绝覆盖") from None
