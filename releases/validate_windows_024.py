# SPDX-License-Identifier: Apache-2.0
"""校验固定 Windows 原生产物的摘要、完整性和随包案例布局。"""

import hashlib
import io
import json
import posixpath
import sys
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def workbook_project(content: bytes) -> str:
    """读取案例“项目信息”工作表 B2，不依赖 Excel 或其他包。"""
    main = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    with zipfile.ZipFile(io.BytesIO(content)) as book:
        sheets = ElementTree.fromstring(book.read("xl/workbook.xml"))
        matches = [s for s in sheets.iter(main + "sheet") if s.get("name") == "项目信息"]
        if len(matches) != 1:
            raise ValueError("工作簿项目信息表不唯一")
        relationship = matches[0].get(rel)
        links = ElementTree.fromstring(book.read("xl/_rels/workbook.xml.rels"))
        targets = [x.get("Target", "") for x in links if x.get("Id") == relationship]
        if len(targets) != 1:
            raise ValueError("工作簿项目信息关系无效")
        target = targets[0].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        target = posixpath.normpath(target)
        if not target.startswith("xl/worksheets/"):
            raise ValueError("工作簿项目信息关系路径无效")
        sheet = ElementTree.fromstring(book.read(target))
        cells = [c for c in sheet.iter(main + "c") if c.get("r") == "B2"]
        if len(cells) != 1:
            raise ValueError("工作簿项目名称单元格无效")
        cell = cells[0]
        if cell.get("t") == "s":
            shared = ElementTree.fromstring(book.read("xl/sharedStrings.xml"))
            value = cell.findtext(main + "v")
            index = int(value) if value is not None else -1
            entries = list(shared.iter(main + "si"))
            if not 0 <= index < len(entries):
                raise ValueError("工作簿共享字符串索引无效")
            return "".join(t.text or "" for t in entries[index].iter(main + "t"))
        return "".join(t.text or "" for t in cell.iter(main + "t"))


def validate(manifest: dict, directory: Path) -> None:
    """任何摘要、内容或路径不符都拒绝发布。"""
    bundle_name = manifest["bundle"]
    if Path(bundle_name).name != bundle_name or not bundle_name.endswith(".zip"):
        raise ValueError("无效包名")
    bundle = directory / bundle_name
    sidecar = directory / (bundle_name + ".sha256")
    digest = sha256(bundle)
    fields = sidecar.read_text(encoding="utf-8-sig").strip().split(maxsplit=1)
    if (
        bundle.stat().st_size != manifest["bytes"]
        or digest != manifest["sha256"]
        or len(fields) != 2
        or fields[0].lower() != digest
        or fields[1].lstrip("*") != bundle_name
    ):
        raise ValueError("ZIP 摘要、大小或 sidecar 不一致")
    app = manifest["app"]
    required = set(manifest["cases"])
    expected_cases = {"甲醛示例", "材料抗拉强度", "颗粒振实密度", "数字多用表", "GB-T合成检测"}
    if (
        len(manifest["cases"]) != len(expected_cases)
        or required != expected_cases
        or app != "能力验证样品评价与定值工具"
    ):
        raise ValueError("应用名或五案例清单无效")
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or archive.testzip() is not None:
            raise ValueError("ZIP 条目重复或校验失败")
        if any(n.startswith("/") or "\\" in n or ".." in PurePosixPath(n).parts for n in names):
            raise ValueError("ZIP 包含不安全路径")
        if archive.read(f"{app}/{app}.exe")[:2] != b"MZ":
            raise ValueError("不是 Windows EXE")
        prefix = f"{app}/示例案例/"
        case_paths = [n for n in names if n.startswith(prefix) and n.endswith(".xlsx")]
        cases = {PurePosixPath(n).stem for n in case_paths}
        if (
            len(case_paths) != len(expected_cases)
            or cases != required
            or any(PurePosixPath(n).parent.as_posix() != prefix.rstrip("/") for n in case_paths)
        ):
            raise ValueError("五案例布局不符")
        copies = [
            archive.read(f"{app}/甲醛示例.xlsx"),
            archive.read(f"{app}/_internal/windows/甲醛示例.xlsx"),
            archive.read(prefix + "甲醛示例.xlsx"),
        ]
        if len(set(copies)) != 1 or prefix + "案例说明.txt" not in names:
            raise ValueError("甲醛副本或案例索引不符")
        for name, project in (
            ("材料抗拉强度", "材料抗拉强度"),
            ("颗粒振实密度", "颗粒振实密度"),
            ("GB-T合成检测", "合成检测示例"),
        ):
            if workbook_project(archive.read(prefix + name + ".xlsx")) != project:
                raise ValueError(f"工作簿内项目名称不符：{name}")
        for item in ("LICENSE", "NOTICE", "THIRD_PARTY_LICENSES.md"):
            if f"{app}/{item}" not in names:
                raise ValueError("缺少许可文件")
        if not any(n.endswith("Python-LICENSE.txt") for n in names):
            raise ValueError("缺少 Python 许可")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: python validate_windows.py MANIFEST ARTIFACT_DIRECTORY")
    try:
        validate(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")), Path(sys.argv[2]))
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        raise SystemExit(f"Windows 产物校验失败：{error}") from error
    print("Windows artifact verified.")
