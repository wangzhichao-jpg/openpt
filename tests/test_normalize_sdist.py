# SPDX-License-Identifier: Apache-2.0
"""归一化 sdist 去除用户元数据并固定时间。"""

import io
import runpy
import tarfile
from pathlib import Path

import pytest


def test_normalized_sdist_reproducible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    script = Path(__file__).resolve().parents[1] / "tools/normalize_sdist.py"
    normalize = runpy.run_path(str(script))["main"]
    archives = []
    for i in range(2):
        path = tmp_path / f"input{i}.tar.gz"
        with tarfile.open(path, "w:gz", format=tarfile.PAX_FORMAT) as tar:
            item = tarfile.TarInfo("project/文件.txt")
            item.size = 3
            item.mtime = 100 + i
            item.uid = i + 10
            item.uname = f"user{i}"
            item.pax_headers = {"mtime": str(item.mtime), "atime": str(200 + i)}
            tar.addfile(item, io.BytesIO(b"abc"))
        normalize(path)
        archives.append(path.read_bytes())
        with tarfile.open(path, "r:gz") as tar:
            member = tar.getmembers()[0]
            assert member.uid == member.gid == 0
            assert member.uname == member.gname == "root"
            assert member.mtime == 1700000000
            assert "atime" not in member.pax_headers
    assert archives[0] == archives[1]
