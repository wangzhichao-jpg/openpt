# SPDX-License-Identifier: Apache-2.0
"""按已核准的 tag 和清单，通过 release ID 安全发布 Windows 产物。"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from validate_windows import sha256, validate

TAG = "v0.2.2"
TITLE = "能力验证样品评价与定值工具 0.2.2 · Windows免安装版"


def gh(*args: str) -> str:
    process = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if process.returncode:
        # 命令只包含公开 API 路径及普通字段，不打印令牌或上传地址。
        endpoint = next((x for x in args if x.startswith("repos/")), args[0])
        raise RuntimeError(f"GitHub endpoint {endpoint} 失败：{process.stderr.strip()}")
    return process.stdout


def api(path: str) -> dict[str, Any]:
    return json.loads(gh("api", path))


def list_pages(path: str) -> list[dict[str, Any]]:
    pages = json.loads(gh("api", "--paginate", "--slurp", path))
    return [item for page in pages for item in page]


def matching_releases(root: str) -> list[dict[str, Any]]:
    all_releases = list_pages(f"{root}/releases?per_page=100")
    matches = [r for r in all_releases if r.get("tag_name") == TAG or r.get("name") == TITLE]
    # 只读诊断：先列出候选，不通过 by-tag 查询推断草稿不存在。
    print(
        "Release 候选："
        + json.dumps(
            [
                {
                    k: r.get(k)
                    for k in ("id", "tag_name", "name", "draft", "prerelease", "target_commitish")
                }
                for r in matches
            ],
            ensure_ascii=False,
        ),
        flush=True,
    )
    if len(matches) > 1:
        raise ValueError("发现多个标签或标题匹配的 Release，停止自动发布")
    return matches


def check_release(release: dict[str, Any]) -> int:
    problems = []
    if release.get("name") != TITLE:
        problems.append("name")
    if release.get("tag_name") != TAG:
        problems.append("tag_name")
    if not isinstance(release.get("id"), int) or isinstance(release.get("id"), bool):
        problems.append("id")
    if not isinstance(release.get("draft"), bool):
        problems.append("draft")
    if not isinstance(release.get("prerelease"), bool):
        problems.append("prerelease")
    if release.get("prerelease") is True and release.get("draft") is False:
        problems.append("已发布的 prerelease")
    if problems:
        raise ValueError("现有 Release 字段不符：" + ", ".join(problems))
    return release["id"]


def check_tag(root: str, source_sha: str) -> None:
    tag = api(f"{root}/git/ref/tags/{TAG}")
    obj = tag.get("object", {})
    if obj.get("type") not in (None, "commit") or obj.get("sha") != source_sha:
        raise ValueError("tag 不指向被核准的源码提交")


def checked_assets(
    root: str, release_id: int, expected: dict[str, tuple[int, str]], *, allow_pending: bool = False
) -> list[dict]:
    assets = list_pages(f"{root}/releases/{release_id}/assets?per_page=100")
    names = [item["name"] for item in assets]
    print(
        "附件只读诊断："
        + json.dumps(
            [
                {k: item.get(k) for k in ("id", "name", "state", "size", "digest")}
                for item in assets
            ],
            ensure_ascii=False,
        ),
        flush=True,
    )
    if len(names) != len(set(names)) or any(name not in expected for name in names):
        raise ValueError("现有 Release 含重复或未核准附件：" + repr(names))
    for item in assets:
        expected_size, expected_digest = expected[item["name"]]
        if item.get("state") != "uploaded" or item["size"] != expected_size:
            raise ValueError("现有附件状态或大小不一致，拒绝覆盖")
        if item.get("digest") != expected_digest and not (
            allow_pending and item.get("digest") is None
        ):
            raise ValueError("现有附件摘要或大小不一致，拒绝覆盖")
    return assets


def diagnostic(root: str, release_id: int | None) -> None:
    """写请求失败后只读检查，不重复请求或吞掉原异常。"""
    try:
        matches = matching_releases(root)
        ids = {item["id"] for item in matches if isinstance(item.get("id"), int)}
        if release_id is not None:
            ids.add(release_id)
        for item_id in sorted(ids):
            details = api(f"{root}/releases/{item_id}")
            assets = list_pages(f"{root}/releases/{item_id}/assets?per_page=100")
            print(
                f"写入后只读核查：release={item_id} draft={details.get('draft')} "
                f"attachments={[a.get('name') for a in assets]}",
                flush=True,
            )
    except Exception as error:
        print(f"写入后只读核查未完成：{error}", file=sys.stderr, flush=True)


def upload(repo: str, release_id: int, file: Path) -> None:
    """只向 GitHub 官方 uploads 域发送令牌，禁止 HTTP 重定向。"""
    url = (
        f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets?"
        + urllib.parse.urlencode({"name": file.name})
    )
    request = urllib.request.Request(
        url,
        data=file.read_bytes(),
        method="POST",
        headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/octet-stream",
        },
    )

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(
            self, req: Any, fp: Any, code: Any, msg: Any, headers: Any, newurl: Any
        ) -> None:
            return None

    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=180) as response:
            if response.status != 201:
                raise RuntimeError(f"上传附件 HTTP {response.status}")
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"GitHub uploads endpoint releases/{release_id}/assets HTTP {error.code}"
        ) from None


def main(manifest_path: Path, directory: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate(manifest, directory)
    repo = os.environ["GITHUB_REPOSITORY"]
    root = f"repos/{repo}"
    # 既有 tag 必须直接指向已验收源码，不允许触发隐式 tag 创建。
    check_tag(root, manifest["source_sha"])
    matches = matching_releases(root)
    bundle = directory / manifest["bundle"]
    sidecar = directory / (manifest["bundle"] + ".sha256")
    expected = {p.name: (p.stat().st_size, "sha256:" + sha256(p)) for p in (bundle, sidecar)}
    if not matches:
        raise ValueError("未找到已知草稿，拒绝创建新 Release")
    release_id = check_release(matches[0])
    if release_id != 444316593:
        raise ValueError(f"候选 Release ID 不符：{release_id}")
    release = api(f"{root}/releases/{release_id}")
    if check_release(release) != release_id:
        raise ValueError("列表与 ID 查询返回的 Release 不一致")
    print(
        "Release 详情："
        + json.dumps(
            {
                k: release.get(k)
                for k in ("id", "name", "tag_name", "draft", "prerelease", "target_commitish")
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    existing = checked_assets(root, release_id, expected)
    print("已有附件：" + json.dumps([a["name"] for a in existing], ensure_ascii=False), flush=True)
    if release["draft"] and release["prerelease"]:
        check_tag(root, manifest["source_sha"])
        try:
            gh(
                "api",
                "--method",
                "PATCH",
                f"{root}/releases/{release_id}",
                "-F",
                "prerelease=false",
                "-f",
                f"target_commitish={manifest['source_sha']}",
            )
        except Exception:
            diagnostic(root, release_id)
            raise
        release = api(f"{root}/releases/{release_id}")
        if check_release(release) != release_id or release["prerelease"] or not release["draft"]:
            raise ValueError("草稿元数据规范化后状态不符")
    if not release["draft"] and len(existing) != len(expected):
        raise ValueError("现有正式 Release 附件不完整，拒绝修改")
    for file in (bundle, sidecar):
        if not any(item["name"] == file.name for item in existing):
            try:
                upload(repo, release_id, file)
            except Exception:
                diagnostic(root, release_id)
                raise
    for _ in range(12):
        uploaded = checked_assets(root, release_id, expected, allow_pending=True)
        if {a["name"] for a in uploaded} == set(expected) and all(
            a.get("digest") == expected[a["name"]][1] for a in uploaded
        ):
            break
        time.sleep(5)
    else:
        raise ValueError("远端附件尚未齐全，拒绝发布")
    if release["draft"]:
        check_tag(root, manifest["source_sha"])
        try:
            gh("api", "--method", "PATCH", f"{root}/releases/{release_id}", "-F", "draft=false")
        except Exception:
            diagnostic(root, release_id)
            raise
    final = api(f"{root}/releases/{release_id}")
    if check_release(final) != release_id or final["draft"] or final["prerelease"]:
        raise ValueError("Release 尚未正式发布")
    print("Verified Windows release is published.")


if __name__ == "__main__":
    try:
        main(Path(sys.argv[1]), Path(sys.argv[2]))
    except (ValueError, OSError, RuntimeError, KeyError, IndexError) as error:
        raise SystemExit(f"发布中止：{error}") from error
