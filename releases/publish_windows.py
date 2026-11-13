# SPDX-License-Identifier: Apache-2.0
"""仅发布经过固定清单校验的 Windows 产物；已有资产不覆盖。"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from validate_windows import sha256, validate

TAG = "v0.2.2"
TITLE = "能力验证样品评价与定值工具 0.2.2 · Windows免安装版"


def gh(*args: str, missing_ok: bool = False) -> str | None:
    process = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if process.returncode:
        if missing_ok and "HTTP 404" in process.stderr:
            return None
        raise RuntimeError(f"gh {args[0]} 失败：{process.stderr.strip()}")
    return process.stdout


def api(path: str, missing_ok: bool = False) -> dict | None:
    result = gh("api", path, missing_ok=missing_ok)
    return json.loads(result) if result is not None else None


def main(manifest_path: Path, directory: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate(manifest, directory)
    repo = os.environ["GITHUB_REPOSITORY"]
    root = f"repos/{repo}"
    tag = api(f"{root}/git/ref/tags/{TAG}", missing_ok=True)
    if tag is None:
        raise ValueError("必须预先建立指向已核准源码的 tag")
    commit = api(f"{root}/commits/{TAG}")
    if commit is None or commit["sha"] != manifest["source_sha"]:
        raise ValueError("现有 tag 不指向被核准的源码提交")
    release = api(f"{root}/releases/tags/{TAG}", missing_ok=True)
    bundle = directory / manifest["bundle"]
    sidecar = directory / (manifest["bundle"] + ".sha256")
    expected = {p.name: (p.stat().st_size, "sha256:" + sha256(p)) for p in (bundle, sidecar)}
    if release is None:
        notes = (
            "1. 下载附件中的 ZIP。\n"
            "2. 将 ZIP 全部解压。\n"
            f"3. 双击 `{manifest['app']}.exe`。\n\n"
            "案例：甲醛示例、金属材料抗拉强度、粉末振实密度、数字多用表。\n"
            "无需安装 Python 或管理员权限。\n\n"
            f"源码提交：`{manifest['source_sha']}`\n"
            f"ZIP SHA-256：`{manifest['sha256']}`\n"
        )
        note_file = directory / "release-notes.md"
        note_file.write_text(notes, encoding="utf-8")
        gh(
            "release",
            "create",
            TAG,
            "--draft",
            "--verify-tag",
            "--title",
            TITLE,
            "--notes-file",
            str(note_file),
        )
        release = api(f"{root}/releases/tags/{TAG}")
    if release is None:
        raise RuntimeError("无法读取 release")
    if release.get("name") != TITLE or release.get("tag_name") != TAG or release.get("prerelease"):
        raise ValueError("现有 release 标题、标签或类型不一致")
    commit = api(f"{root}/commits/{TAG}")
    if commit is None or commit["sha"] != manifest["source_sha"]:
        raise ValueError("tag 与被核准的源码提交不一致")

    def assets() -> list[dict]:
        payload = gh("api", f"{root}/releases/{release['id']}/assets?per_page=100")
        return json.loads(payload or "[]")

    existing = assets()
    if any(item["name"] not in expected for item in existing):
        raise ValueError("现有 release 包含未核准附件")
    if len({item["name"] for item in existing}) != len(existing):
        raise ValueError("现有 release 有重复附件")
    for item in existing:
        if (
            item.get("state") != "uploaded"
            or (item["size"], item.get("digest")) != expected[item["name"]]
        ):
            raise ValueError("现有附件摘要或大小不一致，拒绝覆盖")
    if not release["draft"] and len(existing) != len(expected):
        raise ValueError("现有正式 release 附件不完整，拒绝修改")
    for file in (bundle, sidecar):
        if not any(item["name"] == file.name for item in existing):
            gh("release", "upload", TAG, str(file))
    for _ in range(12):
        uploaded = assets()
        if {a["name"] for a in uploaded} == set(expected) and all(
            a.get("state") == "uploaded" and (a["size"], a.get("digest")) == expected[a["name"]]
            for a in uploaded
        ):
            break
        time.sleep(5)
    else:
        raise ValueError("远端附件摘要、大小或名称不一致")
    if release["draft"]:
        gh("api", "--method", "PATCH", f"{root}/releases/{release['id']}", "-F", "draft=false")
    final = api(f"{root}/releases/tags/{TAG}")
    if final is None or final["draft"]:
        raise ValueError("release 尚未正式发布")
    print("Verified Windows release is published.")


if __name__ == "__main__":
    try:
        main(Path(sys.argv[1]), Path(sys.argv[2]))
    except (ValueError, OSError, RuntimeError, KeyError, IndexError) as error:
        raise SystemExit(f"发布中止：{error}") from error
