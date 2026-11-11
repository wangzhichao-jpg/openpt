# SPDX-License-Identifier: Apache-2.0
"""GL002 4.4、4.5：已知指定值和评价标准差的 z。"""

import math
from typing import Any


def zscore(
    value: float,
    assigned: float,
    sigma: float,
    satisfactory: float = 2.0,
    unsatisfactory: float = 3.0,
) -> dict[str, Any]:
    """按 GL002 4.4 式(3) 计算 z=(x-X)/σ，并按 4.5 评价。"""
    if (
        not all(
            isinstance(x, (float, int)) and not isinstance(x, bool) and math.isfinite(x)
            for x in (value, assigned, sigma, satisfactory, unsatisfactory)
        )
        or sigma <= 0
        or not 0 <= satisfactory < unsatisfactory
    ):
        raise ValueError("z 输入必须有限、标准差为正且阈值有序")
    z = (value - assigned) / sigma
    if not math.isfinite(z):
        raise ValueError("z 数值溢出")
    return {
        "z": z,
        "status": "OK",
        "classification": "满意"
        if abs(z) <= satisfactory
        else "可疑"
        if abs(z) < unsatisfactory
        else "不满意",
    }
