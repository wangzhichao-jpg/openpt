# SPDX-License-Identifier: Apache-2.0
"""线性趋势稳定性：普通最小二乘及指定时间跨度的不确定度。"""

import math
from collections import defaultdict
from typing import Any

import numpy as np
from scipy.stats import t as student_t

from ..errors import InputError
from .decision import compare


def fit(x: list[float], y: list[float], alpha: float = 0.05) -> dict[str, Any]:
    """拟合截距和斜率；零残差的 0/0 不冒充可检验的稳定性。"""
    try:
        if any(isinstance(value, (bool, np.bool_)) for value in x) or any(
            isinstance(value, (bool, np.bool_)) for value in y
        ):
            raise ValueError("布尔值不是测量数")
        xx = np.asarray(x, dtype=float)
        yy = np.asarray(y, dtype=float)
    except (TypeError, ValueError, OverflowError):
        raise InputError("趋势数据须为有限数值序列") from None
    if xx.ndim != 1 or yy.ndim != 1 or len(xx) != len(yy) or len(xx) < 3:
        raise InputError("趋势拟合需要至少三个成对观测值")
    if not np.isfinite(xx).all() or not np.isfinite(yy).all() or not 0 < alpha < 1:
        raise InputError("趋势数据须为有限数值，alpha 须在 0 与 1 之间")
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        x_bar, y_bar = float(xx.mean()), float(yy.mean())
        centered = xx - x_bar
        sxx = float(np.dot(centered, centered))
        if not math.isfinite(sxx) or sxx <= 0:
            raise InputError("趋势时间点须有变化且数值不能溢出")
        b1 = float(np.dot(centered, yy - y_bar) / sxx)
        b0 = y_bar - b1 * x_bar
        residuals = yy - (b0 + b1 * xx)
        df = len(xx) - 2
        s = math.sqrt(float(np.dot(residuals, residuals)) / df)
        sb1 = s / math.sqrt(sxx)
        critical = float(student_t.ppf(1 - alpha / 2, df))
        threshold = critical * sb1
    if not all(math.isfinite(v) for v in (x_bar, y_bar, b0, b1, s, sb1, critical, threshold)):
        raise InputError("趋势拟合数值溢出")
    t_stat = abs(b1) / sb1 if sb1 > 0 else None
    p = float(2 * student_t.sf(t_stat, df)) if t_stat is not None else (0.0 if b1 else None)
    indeterminate = sb1 == 0 and b1 == 0
    return {
        "n": len(xx),
        "df": df,
        "x_bar": x_bar,
        "y_bar": y_bar,
        "b1": b1,
        "b0": b0,
        "s_residuals": s,
        "s_b1": sb1,
        "t_stat": t_stat,
        "t_critical": critical,
        "p_value": p,
        "threshold": threshold,
        "confidence_interval": [b1 - threshold, b1 + threshold],
        "stable": None if indeterminate else compare(abs(b1), threshold) < 0,
        "status": "INDETERMINATE" if indeterminate else "OK",
        "design_status": "DESIGN_WARNING" if df == 1 else "OK",
        "design_warnings": ["仅三个时间点，自由度为 1，须审核设计"] if df == 1 else [],
    }


def fit_series(
    records: list[dict[str, Any]], aggregate: str = "per_series", alpha: float = 0.05
) -> dict[str, Any]:
    """按序列拟合或先按时间取均值；不同单位和缺失/重复记录不混用。"""
    if aggregate not in ("per_series", "time_mean"):
        raise InputError("trend_aggregate 应为 per_series 或 time_mean")
    grouped: dict[str, list[tuple[float, float]]] = defaultdict(list)
    points: dict[str, dict[float, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    units: dict[str, str] = {}
    condition_units: dict[str, str] = {}
    for row in records:
        try:
            name, unit = row["series"], row["time_unit"]
            if isinstance(row["x"], bool) or isinstance(row["y"], bool):
                raise ValueError("布尔值不是测量值")
            x, y = float(row["x"]), float(row["y"])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise InputError("趋势数据须填写序列名、时间、时间单位及数值") from None
        if not isinstance(name, str) or not name.strip() or unit not in ("天", "月", "次"):
            raise InputError("趋势序列名不能为空，时间单位须为天、月或次")
        if not math.isfinite(x) or not math.isfinite(y):
            raise InputError("趋势时间和数值须为有限数")
        condition = row.get("condition") or ""
        if not isinstance(condition, str) or condition == "时间均值":
            raise InputError("趋势条件须为文字且不能使用保留名称时间均值")
        series_name = f"{condition}/{name}" if condition else name
        group_name = condition or "时间均值"
        if series_name in units and units[series_name] != unit:
            raise InputError("同一序列的时间单位须一致")
        units[series_name] = unit
        if (
            aggregate == "time_mean"
            and group_name in condition_units
            and condition_units[group_name] != unit
        ):
            raise InputError("同一条件按时间均值拟合时单位须一致")
        condition_units[group_name] = unit
        if name in points[group_name][x]:
            raise InputError("同一条件、序列和时间点不得重复")
        points[group_name][x][name] = y
        grouped[series_name].append((x, y))
    if not units:
        raise InputError("趋势序列不能为空")
    if aggregate == "time_mean":
        grouped = {}
        units = {}
        for condition, timepoints in points.items():
            sets = [set(group) for group in timepoints.values()]
            if not sets or any(s != sets[0] for s in sets):
                raise InputError("按时间均值拟合须为每个时间点提供相同样品集合")
            grouped[condition] = [(x, sum(v.values()) / len(v)) for x, v in timepoints.items()]
            units[condition] = condition_units[condition]
    result = {}
    for name, values in grouped.items():
        ordered = sorted(values)
        result[name] = {
            **fit([v[0] for v in ordered], [v[1] for v in ordered], alpha),
            "time_unit": units[name],
        }
    return result


def stability_uncertainty(
    short_slope_se: float, short_span: float, long_slope_se: float, long_span: float
) -> dict[str, float]:
    """按登记的同单位时间跨度合成短期与长期分量，不自动计入预算。"""
    values = (short_slope_se, short_span, long_slope_se, long_span)
    if any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
        for v in values
    ):
        raise InputError("趋势标准误和时间跨度须为非负有限数")
    short, long = short_slope_se * short_span, long_slope_se * long_span
    total = math.hypot(short, long)
    if not math.isfinite(total):
        raise InputError("稳定性不确定度数值溢出")
    return {"u_short": short, "u_long": long, "u_stab": total}


def configured_uncertainty(series: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any] | None:
    """解析完整配置并记录短长期时长；不与手工预算静默合并。"""
    keys = ("trend_short_series", "trend_short_span", "trend_long_series", "trend_long_span")
    present = [cfg.get(key) not in (None, "") for key in keys]
    if not any(present):
        return None
    if not all(present):
        raise InputError("趋势不确定度须同时登记短期、长期序列及时长")
    short, long = str(cfg[keys[0]]), str(cfg[keys[2]])
    if short == long:
        raise InputError("短期和长期趋势分量须来自不同序列，不能重复计入")
    if short not in series or long not in series:
        raise InputError("趋势不确定度序列不存在")
    result: dict[str, Any] = stability_uncertainty(
        series[short]["s_b1"], cfg[keys[1]], series[long]["s_b1"], cfg[keys[3]]
    )
    result.update(
        {
            "short_series": short,
            "long_series": long,
            "short_span": cfg[keys[1]],
            "long_span": cfg[keys[3]],
        }
    )
    return result
