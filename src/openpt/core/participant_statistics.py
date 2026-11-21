# SPDX-License-Identifier: Apache-2.0
"""参加者结果的描述统计，不改变评价或剔除数据。"""

import math
import statistics
from typing import Any

from ..errors import InputError
from .robust import median_niqr


def participant_statistics(values: list[float], quantile_method: str) -> dict[str, Any]:
    """GL002 附录 B 表 B1；算术均值与样本标准差仅供参考。"""
    if not values or any(not math.isfinite(value) for value in values):
        raise InputError("参加者统计量需要有限数值", sheet="参加者结果")
    try:
        median = statistics.median(values)
        mean = statistics.mean(values)
        sd = statistics.stdev(values) if len(values) >= 2 else None
        minimum, maximum = min(values), max(values)
        span = maximum - minimum
        niqr = median_niqr(values, quantile_method).niqr if len(values) >= 2 else None
        robust_cv = niqr / median * 100 if median != 0 and niqr is not None else None
        if any(
            v is not None and not math.isfinite(v)
            for v in (median, mean, sd, span, niqr, robust_cv)
        ):
            raise OverflowError
    except InputError:
        raise
    except (OverflowError, ValueError):
        raise InputError("参加者描述统计数值超出范围", sheet="参加者结果") from None
    return {
        "n": len(values),
        "median": median,
        "niqr": niqr,
        "robust_cv_percent": robust_cv,
        "min": minimum,
        "max": maximum,
        "range": span,
        "mean": mean,
        "sd": sd,
        "quantile_method": quantile_method,
    }
