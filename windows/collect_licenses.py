# SPDX-License-Identifier: Apache-2.0
"""收集构建环境中实际运行依赖和 Python 的随附许可证。"""

import shutil
import sys
from importlib import metadata
from pathlib import Path

out = Path(sys.argv[1]) / "第三方许可证"
out.mkdir(parents=True, exist_ok=True)
for name in (
    "numpy",
    "scipy",
    "openpyxl",
    "python-docx",
    "et-xmlfile",
    "lxml",
    "typing-extensions",
    "pyinstaller",
):
    distribution = metadata.distribution(name)
    count = 0
    for item in distribution.files or []:
        text = str(item).replace("\\", "/")
        lower = text.lower()
        if ".dist-info/" not in lower or not any(
            part in lower for part in ("license", "licence", "copying", "notice")
        ):
            continue
        source = Path(distribution.locate_file(item))
        if source.is_file():
            relative = text.split(".dist-info/", 1)[1]
            target = out / name / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            count += 1
    if not count:
        raise RuntimeError(f"未找到 {name} 的随附许可证")
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if not python_license.is_file():
    raise RuntimeError("未找到 Python 许可证")
shutil.copy2(python_license, out / "Python-LICENSE.txt")
# 官方 Windows Python 安装包不一定带 Tcl 的 license.terms；保留 Tcl 8.6
# Debian 源码包版权清单（其中含原许可全文），并复制所装 Tk 的许可。
shutil.copy2(Path(__file__).with_name("Tcl-8.6-copyright.txt"), out / "Tcl-8.6-copyright.txt")
matches = list((Path(sys.base_prefix) / "tcl").glob("tk*/license.terms"))
if not matches:
    raise RuntimeError("未找到 Tk 许可证")
shutil.copy2(matches[0], out / "tk-license.terms")
