# SPDX-License-Identifier: Apache-2.0
"""可选趋势图；没有绘图库时不影响计算。"""

from collections import defaultdict
from io import BytesIO
from typing import Any


def trend_plot(
    records: list[dict[str, Any]], name: str, aggregate: str, fit: dict[str, Any]
) -> BytesIO | None:
    """仅画与当前拟合对应的数据，调用方决定是否插入报告。"""
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
    except ImportError:
        return None
    by_time: dict[float, list[float]] = defaultdict(list)
    for row in records:
        condition = row.get("condition") or ""
        series = f"{condition}/{row['series']}" if condition else row["series"]
        group = condition or "时间均值"
        if (aggregate == "per_series" and series == name) or (
            aggregate == "time_mean" and group == name
        ):
            by_time[float(row["x"])].append(float(row["y"]))
    if not by_time:
        return None
    x = sorted(by_time)
    y = [sum(by_time[t]) / len(by_time[t]) for t in x]
    figure = Figure(figsize=(5.8, 2.8), layout="constrained")
    FigureCanvasAgg(figure)
    axis = figure.subplots()
    axis.scatter(x, y, label="observed")
    axis.plot(x, [fit["b0"] + fit["b1"] * t for t in x], label="linear fit")
    axis.set_xlabel("time")
    axis.set_ylabel("value")
    axis.legend()
    stream = BytesIO()
    figure.savefig(stream, format="png", dpi=150)
    stream.seek(0)
    return stream
