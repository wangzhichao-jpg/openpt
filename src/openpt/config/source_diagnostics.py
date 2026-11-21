# SPDX-License-Identifier: Apache-2.0
"""随包示例来源原文与定值方法的非阻断诊断。"""

import hashlib
import json
from importlib.resources import files
from typing import Any

FIELDS = {
    "source": ("指定值与不确定度", "assigned_config"),
    "uncertainty_source": ("指定值与不确定度", "assigned_config"),
    "sigma_procedure": ("指定值与不确定度", "assigned_config"),
    "stability_disposition_reason": ("指定值与不确定度", "assigned_config"),
    "sigma_source": ("方法配置", "config"),
    "reference_source": ("方法配置", "config"),
    "trend_source": ("方法配置", "config"),
}
CONTRADICTORY_KEYWORDS = {
    "known": ("参加者", "公议", "算法a"),
    "certified": ("参加者", "公议", "算法a"),
    "reference": ("参加者", "公议", "算法a"),
    "expert_consensus": ("参加者", "公议", "算法a"),
    "participant_consensus": ("有证", "crm", "标准物质", "参考实验室"),
}


def participant_digest(data: dict[str, Any]) -> str:
    """按编号和值及可选不确定度比较参加者数据，不依赖行顺序或位置。"""
    rows = [
        [
            str(p["id"]),
            *[
                float(p[key]) if p.get(key) is not None else None
                for key in ("value", "u", "U", "k")
            ],
        ]
        for p in data.get("participants", [])
    ]
    rows.sort(key=lambda row: str(row[0]))
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def example_record(data: dict[str, Any]) -> dict[str, Any]:
    """提取随包工作簿中与来源文字有关的可公开元数据。"""
    descriptions = {
        field: data.get(group, {}).get(field)
        for field, (_, group) in FIELDS.items()
        if isinstance(data.get(group, {}).get(field), str) and data[group][field]
    }
    return {
        "project": data.get("info", {}).get("项目名称"),
        "method": data.get("assigned_config", {}).get("method") or None,
        "participants_sha256": participant_digest(data),
        "fields": descriptions,
    }


def _location(data: dict[str, Any], sheet: str, field: str) -> str:
    cell = data.get("_cells", {}).get((sheet, field), ("", None))[0]
    original = data.get("_source_cells", {}).get(f"{sheet}!{cell}")
    if original:
        sheet, cell = original.rsplit("!", 1)
    return f"『{sheet}』{cell or '位置未记录'}（{field}）"


def source_diagnostics(data: dict[str, Any]) -> list[dict[str, str]]:
    """文本匹配仅提示审核，不推断来源真实情况，不阻止计算。"""
    records = json.loads(
        files("openpt.config").joinpath("example_sources.json").read_text(encoding="utf-8")
    )
    current = example_record(data)
    result = []
    for field, text in current["fields"].items():
        sheet, _ = FIELDS[field]
        origin = _location(data, sheet, field)
        candidates = [row for row in records if text in row["fields"].values()]
        same = any(
            all(row[key] == current[key] for key in ("project", "method", "participants_sha256"))
            for row in candidates
        )
        if candidates and not same:
            result.append(
                {
                    "类型": "示例来源沿用",
                    "层级": "提示",
                    "说明": f"{origin}：来源说明与随包示例原文相同，请按本项目实际情况改写。",
                }
            )
        if field in ("source", "uncertainty_source"):
            compact = "".join(text.casefold().split())
            keywords = CONTRADICTORY_KEYWORDS.get(current["method"], ())
            found = [word for word in keywords if word in compact]
            if found:
                result.append(
                    {
                        "类型": "来源方法矛盾",
                        "层级": "提示",
                        "说明": f"{origin}：来源说明可能与定值方法不一致"
                        f"（method={current['method']}，关键词：{'、'.join(found)}），请核实。",
                    }
                )
    return result
