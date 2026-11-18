# SPDX-License-Identifier: Apache-2.0
"""计算入口与输入预检共用的配置规则。"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuleIssue:
    """一个可定位的配置问题。"""

    field: str
    value: Any
    message: str
    allowed: str
    hint: str


def check_method_config(values: dict[str, Any]) -> list[RuleIssue]:
    """检查明确选择的 GB/T 判据依据。"""
    if values.get("criterion_standard") != "gbt28043":
        return []
    basis = values.get("gbt_criterion_basis")
    if basis == "delta_e" and values.get("delta_e") in (None, ""):
        return [
            RuleIssue(
                "delta_e",
                values.get("delta_e"),
                "所选 gbt_criterion_basis 缺少对应输入",
                "正有限数",
                "填写 delta_e，或选择有对应输入的判据依据",
            )
        ]
    return []
