#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# 以已提交的公开源码运行可选 Wine 验证；不是 Windows 实机测试。
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
image="${OPENPT_WINE_IMAGE:-tobix/pywine:3.12}"
lock="${OPENPT_WINE_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/openpt-wine.lock}"
name="openpt-wine-$(id -u)-$$"
mkdir -p "$(dirname -- "$lock")"
exec 9>"$lock"
flock -n 9 || { echo '已有 Wine 测试正在运行。' >&2; exit 1; }
docker image inspect "$image" >/dev/null || {
    echo '缺少 Wine 镜像；请先核实可靠镜像来源和摘要后安装。' >&2
    exit 1
}
scratch="$(mktemp -d "${TMPDIR:-/tmp}/openpt-wine.XXXXXX")"
cleanup() {
    docker stop "$name" >/dev/null 2>&1 || true
    # 容器以 root 写入，先在隔离容器内删除其产生的文件，再由调用者删除目录。
    docker run --rm --pull=never --entrypoint /bin/sh -v "$scratch:/clean" "$image" \
        -c 'find /clean -mindepth 1 -delete' >/dev/null 2>&1 || true
    rm -rf -- "$scratch"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
mkdir -p "$scratch/work"
git -C "$root" archive HEAD | tar -x -C "$scratch/work"
chmod -R a+rwX "$scratch"
echo "镜像：$image；提交：$(git -C "$root" rev-parse HEAD)"
docker run --rm --name "$name" -e LANG=C.UTF-8 -e LC_ALL=C.UTF-8 \
    -e PYTHONDONTWRITEBYTECODE=1 -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
    -v "$scratch/work:/work" -w /work "$image" /bin/sh -ec '
    python="C:\\Python\\python.exe"
    wine "$python" --version
    wine "$python" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
        "numpy==1.26.4" "scipy==1.13.1" "openpyxl>=3.1.5,<4" \
        "python-docx>=1.2.0,<2" "pytest>=8,<9" "pytest-cov>=6,<8" \
        "hypothesis>=6,<7" "setuptools==80.9.0" wheel
    wine "$python" -m pip install --no-build-isolation --no-deps .
    wine "$python" -m pytest -m "not internal" -p no:cacheprovider -q
    wine "$python" -m openpt demo "Z:\\work\\中文演示"
    test -s /work/中文演示/GL003_A1_计算书.docx
    echo "Wine 公开测试和中文路径 demo 完成。"
'
