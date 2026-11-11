# SPDX-License-Identifier: Apache-2.0
"""GL003 4.1 随机抽样及重复测试次序。"""

import csv
import json
from pathlib import Path
from typing import Any

import numpy as np
from openpyxl import Workbook

from .errors import InputError


def _allocation(sizes: list[int], pick: int) -> list[int]:
    """按比例分配，保证每层至少一个且不超过该层容量。"""
    if not sizes or any(size < 1 for size in sizes) or not len(sizes) <= pick <= sum(sizes):
        raise InputError("抽样数须不小于层数且不大于总体")
    ideals = [pick * size / sum(sizes) for size in sizes]
    counts = [max(1, int(value)) for value in ideals]
    while sum(counts) < pick:
        index = max(
            (i for i in range(len(sizes)) if counts[i] < sizes[i]),
            key=lambda i: (ideals[i] - counts[i], -i),
        )
        counts[index] += 1
    while sum(counts) > pick:
        index = max(
            (i for i in range(len(sizes)) if counts[i] > 1),
            key=lambda i: (counts[i] - ideals[i], -i),
        )
        counts[index] -= 1
    return counts


def sample(
    units: int, pick: int, seed: int, strata: dict[str, list[int]] | None = None
) -> dict[str, Any]:
    """固定 PCG64，逐层无放回抽取，置换盲码及两次重复的检测次序。"""
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (units, pick, seed)):
        raise InputError("总体、抽样数和种子须为整数")
    if units < 1 or pick < 1 or pick > units or seed < 0:
        raise InputError("总体、抽样数或种子无效")
    groups = strata if strata is not None else {"总体": list(range(1, units + 1))}
    if (
        not isinstance(groups, dict)
        or not groups
        or not all(
            isinstance(name, str) and name and isinstance(items, list)
            for name, items in groups.items()
        )
    ):
        raise InputError("分层须为层名到单元编号数组的 JSON 对象")
    flattened = [item for items in groups.values() for item in items]
    if any(isinstance(item, bool) or not isinstance(item, int) for item in flattened):
        raise InputError("分层单元编号须为整数")
    if sorted(flattened) != list(range(1, units + 1)):
        raise InputError("各层必须无重复且完整覆盖 1 至总体数")
    allocation = _allocation([len(items) for items in groups.values()], pick)
    rng = np.random.Generator(np.random.PCG64(seed))
    selected: list[tuple[str, int]] = []
    for (name, items), count in zip(groups.items(), allocation, strict=True):
        selected.extend((name, int(unit)) for unit in rng.choice(items, count, replace=False))
    blind = rng.permutation(pick) + 1
    samples = [
        {"单元编号": unit, "层": name, "盲码": f"B{int(code):06d}"}
        for (name, unit), code in zip(selected, blind, strict=True)
    ]
    tests = [{**entry, "重复编号": repeat} for entry in samples for repeat in (1, 2)]
    order = rng.permutation(len(tests))
    tests = [{"检测顺序": i + 1, **tests[int(index)]} for i, index in enumerate(order)]
    return {
        "population": list(range(1, units + 1)),
        "strata": groups,
        "allocation": dict(zip(groups, allocation, strict=True)),
        "seed": seed,
        "algorithm": "numpy.random.Generator(PCG64)",
        "numpy_version": np.__version__,
        "samples": samples,
        "tests": tests,
        "warnings": ["DESIGN_WARNING：GL003 4.1 均匀性抽样数少于 10"] if pick < 10 else [],
        "note": "每次重复须分别独立取样；随机化不证明取样实际独立。盲码并非密码保护。",
    }


def write_sample(directory: str | Path, record: dict[str, Any]) -> None:
    """写入新目录中的 JSON、CSV 和 XLSX，不覆盖已有目录。"""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=False)
    (target / "sample.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    fields = ["检测顺序", "单元编号", "层", "盲码", "重复编号"]
    with (target / "sample.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in record["tests"]:
            safe_row = dict(row)
            layer = safe_row["层"]
            if layer.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
                safe_row["层"] = "'" + layer
            writer.writerow(safe_row)
    book = Workbook()
    sheet = book.active
    sheet.title = "检测顺序"
    sheet.append(fields)
    for row in record["tests"]:
        sheet.append([row[field] for field in fields])
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = "s"
    book.save(target / "sample.xlsx")
