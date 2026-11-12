# SPDX-License-Identifier: Apache-2.0
"""追加人工决定并生成带决定记录的新计算书版本。"""

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit import MANIFEST, _digest
from .config.catalog import ENUMS
from .errors import InputError
from .report.docx import make_report
from .report.multi import export_reports
from .reproduce import compare_results
from .runs import _calculate_snapshot, verify_directory


def decide(
    root: Path, item: str, decision: str, person: str, note: str, *, allow_new_item: bool = False
) -> dict[str, Any]:
    """在锁内核验快照、追加决定、生成新版本；原始输入和既有报告不修改。"""
    if decision not in ENUMS["decision"]:
        raise InputError("决定只能是接受、退回或需补充")
    if not item.strip() or not person.strip() or len(note) > 10000:
        raise InputError("条目和人员必填，备注不得超过 10000 字符")
    lock = root.with_name(root.name + ".decision.lock")
    try:
        with lock.open("x", encoding="utf-8") as stream:
            stream.write("locked\n")
    except FileExistsError:
        raise InputError("该运行记录正在写入决定") from None
    staging: Path | None = None
    try:
        errors = verify_directory(root)
        if errors:
            raise InputError("运行目录校验失败：" + "；".join(errors))
        result_bytes = (root / "result.json").read_bytes()
        result_hash = hashlib.sha256(result_bytes).hexdigest()
        original_result = json.loads(result_bytes)
        if isinstance(original_result.get("被测量"), dict):
            available = sorted(
                f"被测量:{name}/{key}"
                for name, result in original_result["被测量"].items()
                for key in result
            )
        else:
            available = sorted(original_result)
        custom_item = item not in available
        if custom_item and not allow_new_item:
            raise InputError("结果中不存在该条目；可用条目：" + "、".join(available))
        decisions_path = root / "decisions.jsonl"
        previous = []
        if decisions_path.exists():
            with decisions_path.open(encoding="utf-8") as stream:
                previous = [json.loads(line) for line in stream if line.strip()]
        if any(record.get("result_sha256") != result_hash for record in previous):
            raise InputError("既有决定所依据的结果哈希不一致")
        record: dict[str, Any] = {
            "time": datetime.now(timezone.utc).isoformat(),
            "item": item,
            "decision": decision,
            "by": person,
            "note": note,
            "result_sha256": result_hash,
        }
        if custom_item:
            record["custom_item"] = True
        config = json.loads((root / "config.json").read_text(encoding="utf-8"))
        data, result, differences = _calculate_snapshot(root, config)
        if compare_results(original_result, result):
            raise InputError("当前重算结果与原结果不一致，不能生成决定计算书")
        staging = Path(tempfile.mkdtemp(prefix="openpt-decision-", dir=root.parent))
        existing = list(root.glob("report_rev_*.docx"))
        number = len(existing) + 1
        base = f"report_rev_{number:04d}"
        if any((root / f"{base}.{ext}").exists() for ext in ("docx", "xlsx", "html")):
            raise InputError("计算书版本已存在，拒绝覆盖")
        digest = hashlib.sha256((root / "input" / config["input_file"]).read_bytes()).hexdigest()
        make_report(
            staging / f"{base}.docx",
            data,
            result,
            differences,
            input_sha256=digest,
            decisions=[*previous, record],
        )
        export_reports(
            staging / f"{base}.docx", staging / f"{base}.xlsx", staging / f"{base}.html", result
        )
        # 决定日志是明确允许追加的审计记录；旧记录及原始快照不改写。
        with decisions_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        for ext in ("docx", "xlsx", "html"):
            with (root / f"{base}.{ext}").open("xb") as stream:
                stream.write((staging / f"{base}.{ext}").read_bytes())
        hashes = {}
        for path in sorted(root.rglob("*")):
            if path.is_file() and path != root / MANIFEST:
                with path.open("rb") as stream:
                    hashes[path.relative_to(root).as_posix()] = _digest(stream)
        manifest = staging / MANIFEST
        manifest.write_text(
            json.dumps({"files": hashes}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        manifest.replace(root / MANIFEST)
        return record
    finally:
        if staging is not None:
            shutil.rmtree(staging)
        lock.unlink(missing_ok=True)
