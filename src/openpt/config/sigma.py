# SPDX-License-Identifier: Apache-2.0
"""统一判据标准差的回退规则。"""

from typing import Any


def criterion_sigma(config: dict[str, Any]) -> float | None:
    """优先判据 σ；仅填评价 σ_pt 时用于判据，两个值均填写时各自保留。"""
    value = config.get("sigma")
    if value in (None, ""):
        value = config.get("sigma_pt")
    return None if value in (None, "") else float(value)
