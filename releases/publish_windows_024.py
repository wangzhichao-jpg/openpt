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

from validate_windows_024 import sha256, validate

TAG = "v0.2.4"
TITLE = "能力验证样品评价与定值工具 0.2.4 · Windows免安装版"


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
    if obj.get("type") == "tag":
        # 附注 tag 只解引用一层，必须直接指向被核准的提交。
        annotated = api(f"{root}/git/tags/{obj.get('sha')}")
        if annotated.get("tag") != TAG:
            raise ValueError("附注 tag 名称不符")
        obj = annotated.get("object", {})
        if obj.get("type") != "commit":
            raise ValueError("附注 tag 未直接指向提交")
    if obj.get("type") not in (None, "commit") or obj.get("sha") != source_sha:
        raise ValueError("tag 不指向被核准的源码提交")


def checked_assets(
    root: str, release_id: int, expected: dict[str, tuple[int, str]], *, allow_pending: bool = False
) -> tuple[dict[str, dict], int]:
    assets = list_pages(f"{root}/releases/{release_id}/assets?per_page=100")
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
    if len(set(expected.values())) != len(expected):
        raise ValueError("期望附件摘要和大小不能相同")
    ids = [item.get("id") for item in assets]
    if (
        len(assets) > len(expected)
        or any(not isinstance(i, int) or isinstance(i, bool) or i <= 0 for i in ids)
        or len(ids) != len(set(ids))
    ):
        raise ValueError("附件数量或 ID 无效、重复，拒绝覆盖")
    roles: dict[str, dict] = {}
    pending = 0
    for item in assets:
        if item.get("state") != "uploaded":
            raise ValueError("现有附件状态不符，拒绝覆盖")
        pair = (item.get("size"), item.get("digest"))
        matching = [role for role, values in expected.items() if values == pair]
        if not matching and allow_pending and item.get("digest") is None:
            if not any(size == item.get("size") for size, _ in expected.values()):
                raise ValueError("待核验附件大小不符，拒绝覆盖")
            pending += 1
            continue
        if len(matching) != 1 or matching[0] in roles:
            raise ValueError(f"附件内容未知或角色重复，拒绝覆盖：{item!r}")
        roles[matching[0]] = item
    return roles, pending


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


def upload(repo: str, release_id: int, file: Path) -> dict[str, Any]:
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
            item = json.load(response)
            print(
                "上传响应："
                + json.dumps(
                    {k: item.get(k) for k in ("id", "name", "state", "size", "digest")},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            return item
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
    release_id: int | None = None
    if matches:
        release_id = check_release(matches[0])
        release = api(f"{root}/releases/{release_id}")
        if check_release(release) != release_id:
            raise ValueError("列表与 ID 查询返回的 Release 不一致")
    else:
        notes = (
            "1. 下载附件中的 Windows ZIP。\n2. 将 ZIP 全部解压。\n"
            f"3. 双击 `{manifest['app']}.exe`。\n\n"
            "案例：甲醛示例、材料抗拉强度、颗粒振实密度、数字多用表、GB-T合成检测。\n\n"
            "0.2.4 更新：配置错误一次列出并标明工作表、行号、当前值及修改建议；"
            "能计算但未评价时在窗口、计算书中给出诊断提示及原因；"
            "新增 GB/T 28043 合成示例。\n\n"
            "Apache-2.0 开源；无需安装 Python 或管理员权限。\n\n"
            f"源码提交：`{manifest['source_sha']}`\nZIP SHA-256：`{manifest['sha256']}`\n"
        )
        try:
            response = gh(
                "api",
                "--method",
                "POST",
                f"{root}/releases",
                "-f",
                f"tag_name={TAG}",
                "-f",
                f"target_commitish={manifest['source_sha']}",
                "-f",
                f"name={TITLE}",
                "-f",
                f"body={notes}",
                "-F",
                "draft=true",
                "-F",
                "prerelease=false",
            )
            release = json.loads(response)
            release_id = check_release(release)
        except Exception:
            diagnostic(root, release_id)
            raise
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

    def settled_assets() -> dict[str, dict]:
        for _ in range(12):
            roles, pending = checked_assets(root, release_id, expected, allow_pending=True)
            if not pending:
                return roles
            time.sleep(5)
        raise ValueError("远端附件摘要尚未就绪，拒绝上传或发布")

    existing = settled_assets()
    print("已有附件角色：" + json.dumps(list(existing), ensure_ascii=False), flush=True)
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
        if file.name not in existing:
            try:
                response = upload(repo, release_id, file)
                if (
                    not isinstance(response.get("id"), int)
                    or response.get("state") != "uploaded"
                    or response.get("size") != expected[file.name][0]
                    or response.get("digest") not in (None, expected[file.name][1])
                ):
                    raise ValueError("上传响应与预期内容不符")
                existing = settled_assets()
                if file.name not in existing or existing[file.name]["id"] != response["id"]:
                    raise ValueError("上传响应与远端附件不一致")
            except Exception:
                diagnostic(root, release_id)
                raise
    if set(existing) != set(expected):
        raise ValueError("远端附件尚未齐全，拒绝发布")
    if release["draft"]:
        check_tag(root, manifest["source_sha"])
        try:
            gh(
                "api",
                "--method",
                "PATCH",
                f"{root}/releases/{release_id}",
                "-F",
                "draft=false",
                "-f",
                "make_latest=true",
            )
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
