# SPDX-License-Identifier: Apache-2.0
"""检查可发布工作区和全部可达提交；可选禁用词来自仓库外。"""

import io
import os
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "本机路径": re.compile(rb"/" + rb"home/|[A-Za-z]:\\Users\\", re.I),
    "私有IPv4": re.compile(
        rb"(?<!\d)(?:10\.(?:\d{1,3}\.){2}\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?!\d)"
    ),
    "私钥": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "访问令牌": re.compile(rb"(?:ghp_|github_pat_|sk-)[A-Za-z0-9_\-]{20,}"),
}


def check(label, content, words, depth=0):
    found = []
    for name, pattern in PATTERNS.items():
        if pattern.search(content):
            found.append((label, name))
    low = content.lower()
    for word in words:
        if word in low:
            found.append((label, "禁用词"))
    if depth < 2 and zipfile.is_zipfile(io.BytesIO(content)):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                for name in z.namelist():
                    info = z.getinfo(name)
                    if not info.is_dir() and info.file_size <= 20_000_000:
                        found.extend(check(label + "!" + name, z.read(name), words, depth + 1))
        except (zipfile.BadZipFile, RuntimeError):
            found.append((label, "无法检查压缩文件"))
    if depth < 2:
        try:
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:*") as archive:
                for member in archive.getmembers():
                    found.extend(
                        check(
                            label + "!元数据",
                            (" ".join((member.name, member.uname, member.gname))).encode(),
                            words,
                            depth + 1,
                        )
                    )
                    if member.isfile() and member.size <= 20_000_000:
                        found.extend(
                            check(
                                label + "!" + member.name,
                                archive.extractfile(member).read(),
                                words,
                                depth + 1,
                            )
                        )
        except (tarfile.TarError, OSError, EOFError):
            pass
    return found


def main():
    deny = os.environ.get("OPENPT_DENY_LIST")
    words = (
        []
        if not deny
        else [
            s.strip().lower().encode()
            for s in Path(deny).read_text(encoding="utf-8").splitlines()
            if s.strip() and not s.startswith("#")
        ]
    )
    findings = []
    files = 0
    for p in ROOT.rglob("*"):
        relative = p.relative_to(ROOT)
        if ".git" in relative.parts:
            continue
        if p.is_file():
            files += 1
            findings.extend(check("工作区路径/" + str(relative), str(relative).encode(), words))
            findings.extend(check("工作区/" + str(relative), p.read_bytes(), words))
    revisions = subprocess.check_output(
        ["git", "rev-list", "--all"], cwd=ROOT, text=True
    ).splitlines()
    blobs = {}
    for rev in revisions:
        commit = subprocess.check_output(["git", "cat-file", "commit", rev], cwd=ROOT)
        findings.extend(check("提交/" + rev, commit, words))
        out = subprocess.check_output(["git", "ls-tree", "-r", "-z", rev], cwd=ROOT)
        for item in out.split(b"\0"):
            if not item:
                continue
            meta, filename = item.split(b"\t", 1)
            kind, sha = meta.split()[1:3]
            if kind == b"blob":
                blobs.setdefault(sha, filename.decode("utf-8", "replace"))
    for sha, name in blobs.items():
        content = subprocess.check_output(["git", "cat-file", "blob", sha.decode()], cwd=ROOT)
        findings.extend(check("历史路径/" + name, name.encode(), words))
        findings.extend(check("历史/" + name, content, words))
    for name, reason in sorted(set(findings)):
        print(f"{name}: {reason}")
    print(
        f"工作区文件 {files}；提交 {len(revisions)}；"
        f"历史唯一对象 {len(blobs)}；命中 {len(findings)}"
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
