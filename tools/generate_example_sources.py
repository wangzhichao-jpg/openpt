# SPDX-License-Identifier: Apache-2.0
"""由公开随包工作簿生成来源文字索引，不读取测评人工作簿。"""

import argparse
import json
from pathlib import Path

from openpt.config.source_diagnostics import example_record
from openpt.io.excel import read_workbook

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src/openpt/config/example_sources.json"


def content() -> str:
    paths = sorted(
        [
            *ROOT.joinpath("windows/examples").glob("*.xlsx"),
            ROOT / "windows/甲醛示例.xlsx",
            *ROOT.joinpath("examples").rglob("*.xlsx"),
        ]
    )
    records = []
    for path in paths:
        if path.parent.name == "trace_run" and path.name in ("report.xlsx", "report_rev_0001.xlsx"):
            continue
        data = read_workbook(path)
        parts = data.get("measurands", {}).values() if data.get("measurands") else [data]
        for part in parts:
            record = example_record(part)
            if record["fields"] and record not in records:
                records.append(record)
    records.sort(
        key=lambda item: (str(item["project"]), str(item["method"]), item["participants_sha256"])
    )
    return json.dumps(records, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = content()
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != expected:
            print("随包示例来源索引与公开工作簿不一致")
            return 1
    else:
        TARGET.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
