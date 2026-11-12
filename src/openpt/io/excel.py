# SPDX-License-Identifier: Apache-2.0
"""固定模板、输入校验及来源定位。"""

import csv
import re
import statistics
from collections import defaultdict
from collections.abc import Iterator
from contextlib import suppress
from decimal import Decimal
from math import isfinite
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation

from ..errors import InputError

SHEETS = {
    "项目信息": ["字段", "值"],
    "方法配置": ["字段", "值"],
    "均匀性": ["单元编号", "重复编号", "值", "单位"],
    "稳定性": ["时间组", "单元编号", "重复编号", "值", "单位"],
    "参加者结果": ["参加者编号", "值", "单位"],
    "报告声称值": ["统计量", "声称值", "显示小数位", "来源", "报告模型", "时间组"],
    "指定值与不确定度": ["字段", "值"],
    "算法S": ["标准差或极差", "自由度"],
    "候选批次": [
        "批次编号",
        "物品",
        "目标量值",
        "材质",
        "来源",
        "制备日期",
        "预实验结果",
        "状态",
        "处理理由",
        "关联批次",
    ],
}
PARTICIPANT_OPTIONAL = ("标准不确定度u(x)", "扩展不确定度U(x)", "包含因子k")


def template(path: str | Path) -> None:
    """生成用于 GL003 和 GL002 计算的空白输入模板。"""
    book = Workbook()
    book.remove(book.active)
    instructions = book.create_sheet("填写说明")
    instructions.append(["填写说明", "请填写项目名称、单位及所需数据。"])
    instructions.append(["均匀性", "每个包装单元的每次技术重复填写一行；使用统一单位。"])
    instructions.append(["稳定性", "时间组填写基线、稳定期；复核声称值可指定其他时间组。"])
    instructions.append(["报告声称值", "填写统计量、数值、显示位数、来源和可选报告模型。"])
    instructions.append(["指定值", "按方法登记值、不确定度、来源、σ_pt 确定程序与分量映射。"])
    instructions.append(["参加者结果", "ζ、En 须填写相应不确定度、k，并登记不相关性。"])
    instructions.append(["算法S", "输入至少两个同类型标准差或极差，每行填写相同自由度。"])
    instructions.append(["候选批次", "预实验结果可填英文逗号分隔的数值；软件不自动选择批次。"])
    instructions.column_dimensions["A"].width = 22
    instructions.column_dimensions["B"].width = 80
    for name, headers in SHEETS.items():
        ws = book.create_sheet(name)
        ws.append(headers)
        ws.cell(1, 1).comment = Comment("请按填写说明输入数据；不要输入 Excel 公式。", "OpenPT")
        ws.freeze_panes = "A2"
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = 22
    for col, header in enumerate(("标准不确定度u(x)", "扩展不确定度U(x)", "包含因子k"), 4):
        book["参加者结果"].cell(1, col, header)
    for row in [("项目名称", ""), ("单位", "")]:
        book["项目信息"].append(row)
    for config_row in [
        ("显著性水平（alpha）", 0.05),
        ("均匀性目标标准差（sigma）", ""),
        ("严格均匀性配置（strict_homogeneity）", False),
        ("稳定性方法（stability_method）", "two_sample"),
        ("单均值参考值（reference）", ""),
        ("指定值（assigned）", ""),
        ("能力评定标准差（sigma_pt）", ""),
        ("算法A停止规则（algorithm_a_rule）", "gl002"),
        ("z 值显示小数位（display_z_decimals）", 2),
        ("σ 来源（sigma_source）", ""),
        ("σ 阶段（sigma_stage）", ""),
        ("实验层级（observation_level）", "unit_means"),
        ("实验设计（stability_design）", "independent"),
        ("参考不确定度可忽略（reference_uncertainty_negligible）", True),
        ("参考值来源（reference_source）", ""),
        ("统计量类型（score_type）", "z"),
        ("算法S停止规则（algorithm_s_stop_rule）", "gl002"),
        ("算法S绝对容差（algorithm_s_tolerance）", 1e-12),
        ("算法S最大迭代次数（algorithm_s_max_iterations）", 1000),
        ("判据标准模式（criterion_standard）", "gl003"),
        ("基线均值标准不确定度（stability_u1）", ""),
        ("后续均值标准不确定度（stability_u2）", ""),
        ("报告采用标准模式（report_standard）", ""),
        ("逐时点设置JSON（stability_period_options）", ""),
        ("均匀性预选判据（gbt_hom_rule）", "basic"),
        ("稳定性预选判据（gbt_stability_rule）", "basic"),
    ]:
        book["方法配置"].append(config_row)
    for cell, options in [
        ("B4", '"启用,关闭"'),
        ("B5", '"两均值,单均值"'),
        ("B9", '"gl002,absolute,simplified"'),
        ("B11", '"标准方法精密度,经验值,稳健标准差,其他"'),
        ("B12", '"temporary,final"'),
        ("B13", '"unit_means,all_repeats"'),
        ("B14", '"independent,paired,correlated"'),
        ("B15", '"启用,关闭"'),
        ("B17", '"z,zprime,zeta,En,D,D%,all"'),
        ("B18", '"gl002,absolute"'),
        ("B21", '"gl003,gbt28043"'),
        ("B24", '"gl003,gbt28043"'),
        ("B26", '"basic,extended"'),
        ("B27", '"basic,extended"'),
    ]:
        validation = DataValidation(type="list", formula1=options)
        book["方法配置"].add_data_validation(validation)
        validation.add(book["方法配置"][cell])
    assigned = book["指定值与不确定度"]
    for assigned_row in [
        ("method", ""),
        ("value", ""),
        ("uncertainty", ""),
        ("source", ""),
        ("uncertainty_source", ""),
        ("consensus_method", "robust_mean"),
        ("sigma_temporary", ""),
        ("sigma_final", ""),
        ("sigma_procedure", ""),
        ("u_hom", 0),
        ("u_stab", 0),
        ("hom_mapping", "none"),
        ("stab_mapping", "none"),
        ("hom_in_base", False),
        ("stab_in_base", False),
        ("U_assigned", ""),
        ("k_assigned", ""),
        ("independent", ""),
        ("known_components", ""),
        ("expert_values", ""),
        ("hom_source", "manual"),
        ("u_trans", 0),
        ("trans_mapping", "none"),
        ("trans_in_base", False),
        ("trans_in_stab", False),
    ]:
        assigned.append(assigned_row)
    for cell, options in [
        ("B2", '"known,certified,reference,expert_consensus,participant_consensus"'),
        ("B7", '"robust_mean,median"'),
        ("B13", '"none,assigned,sigma_prime,both"'),
        ("B14", '"none,assigned,sigma_prime,both"'),
        ("B15", '"TRUE,FALSE"'),
        ("B16", '"TRUE,FALSE"'),
        ("B19", '"TRUE,FALSE"'),
        ("B22", '"manual,gbt_ss"'),
        ("B24", '"none,assigned"'),
        ("B25", '"TRUE,FALSE"'),
        ("B26", '"TRUE,FALSE"'),
    ]:
        validation = DataValidation(type="list", formula1=options)
        assigned.add_data_validation(validation)
        validation.add(assigned[cell])
    book.save(path)


def _rows(book: Any, name: str) -> Iterator[Any]:
    """检查表头和公式，再逐行返回原始单元格。"""
    ws = book[name]
    aliases = getattr(book, "_openpt_columns", {}).get(name, {})
    allowed = set(SHEETS[name]) | (set(PARTICIPANT_OPTIONAL) if name == "参加者结果" else set())
    if not isinstance(aliases, dict) or set(aliases) - allowed:
        raise InputError(f"{name}：列映射包含未知字段")
    headers = [ws.cell(1, i).value for i in range(1, max(ws.max_column, len(SHEETS[name])) + 1)]
    if name == "报告声称值" and headers[5] is None:
        headers[5] = "时间组"
    indices = []
    for field in SHEETS[name]:
        label = aliases.get(field, field)
        if not isinstance(label, str) or headers.count(label) != 1:
            raise InputError(f"{name}!1 表头 {label!r} 不存在或不唯一")
        indices.append(headers.index(label) + 1)
    if len(set(indices)) != len(indices):
        raise InputError(f"{name}!1 列映射重复")
    if name == "参加者结果":
        used = set(indices)
        for field in PARTICIPANT_OPTIONAL:
            label = aliases.get(field, field)
            if label not in headers and field not in aliases:
                continue
            if not isinstance(label, str) or headers.count(label) != 1:
                raise InputError(f"{name}!1 可选列 {label!r} 不存在或不唯一")
            index = headers.index(label) + 1
            if index in used:
                raise InputError(f"{name}!1 列映射重复")
            used.add(index)
    for row in range(2, ws.max_row + 1):
        cells = tuple(ws.cell(row, col) for col in indices)
        if not any(c.value is not None for c in cells):
            continue
        if any(c.data_type == "f" for c in cells):
            raise InputError(f"{name}!{cells[0].row}: 不接受公式")
        yield cells


def _numeric(cell: Any, name: str) -> float:
    """读取有限数值，不将文字隐式转换为数值。"""
    if (
        isinstance(cell.value, bool)
        or not isinstance(cell.value, (int, float))
        or not isfinite(cell.value)
    ):
        raise InputError(f"{name}!{cell.coordinate}: 数值无效")
    return float(cell.value)


def _metadata(book: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """读取项目字段和方法配置。"""
    rows = list(_rows(book, "项目信息"))
    info = {str(r[0].value): r[1].value for r in rows if r[0].value}
    locations = {str(r[0].value): r[1].coordinate for r in rows if r[0].value}
    for required in ("项目名称", "单位"):
        if not info.get(required):
            position = locations.get(required)
            location = f"项目信息!{position}" if position else "项目信息"
            raise InputError(f"{location}: {required}必填")
    config = {}
    for row in _rows(book, "方法配置"):
        if not row[0].value:
            continue
        label = str(row[0].value)
        match = re.search(r"（([a-zA-Z_][a-zA-Z_0-9]*)）$", label)
        key = match.group(1) if match else label
        value = row[1].value
        if key in ("strict_homogeneity", "reference_uncertainty_negligible") and value in (
            "启用",
            "关闭",
        ):
            value = value == "启用"
        if key == "stability_method" and value in ("两均值", "单均值"):
            value = {"两均值": "two_sample", "单均值": "one_sample"}[value]
        config[key] = value
    return info, config


def _precision(cell: Any) -> int:
    """优先从 Excel 数字格式提取显示小数位。"""
    number_format = re.search(r"\.([0#]+)", cell.number_format)
    if number_format:
        return len(number_format.group(1))
    exponent = Decimal(str(cell.value)).as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def _observations(
    book: Any, name: str, unit: str, precision: list[int], stability: bool = False
) -> tuple[dict[str, Any], list[str], dict[str, list[str]]]:
    """读取包装单元和重复测量，记录单元格位置。"""
    grouped: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    unit_sources: dict[tuple[str, str], str] = {}
    sources = []
    for row in _rows(book, name):
        group, uid, rep, val, actual_unit = (
            (row[0].value, row[1].value, row[2].value, row[3], row[4].value)
            if stability
            else ("均匀性", row[0].value, row[1].value, row[2], row[3].value)
        )
        if not group or uid is None or rep is None:
            raise InputError(f"{name}!{row[0].row}: 缺少分组或编号")
        if actual_unit != unit:
            raise InputError(f"{name}!{row[-1].coordinate}: 单位不一致")
        key, repeat = (str(group), str(uid)), str(rep)
        if repeat in grouped[key]:
            raise InputError(f"{name}!{row[0].row}: 重复编号")
        grouped[key][repeat] = _numeric(val, name)
        unit_sources[key] = f"{name}!{val.coordinate}"
        precision.append(_precision(val))
        sources.append(f"{name}!{val.coordinate}")
    groups: dict[str, list[list[float]]] = defaultdict(list)
    unit_ids: dict[str, list[str]] = defaultdict(list)
    for (group, uid), values in grouped.items():
        if not stability and len(values) < 2:
            raise InputError(f"{unit_sources[(group, uid)]}: 单元 {uid} 至少需要两次重复")
        groups[group].append(list(values.values()))
        unit_ids[group].append(uid)
    return dict(groups), sources, dict(unit_ids)


def _participants(book: Any, unit: str) -> list[dict[str, Any]]:
    """读取参加者结果和单元格位置。"""
    values = []
    seen: set[str] = set()
    for row in _rows(book, "参加者结果"):
        if row[0].value is None or row[2].value != unit:
            raise InputError(f"参加者结果!{row[0].row}: 编号或单位错误")
        participant_id = str(row[0].value)
        if participant_id in seen:
            raise InputError(f"参加者结果!{row[0].coordinate}: 编号重复")
        seen.add(participant_id)
        participant = {
            "id": str(row[0].value),
            "value": _numeric(row[1], "参加者结果"),
            "source": f"参加者结果!{row[1].coordinate}",
        }
        worksheet = book["参加者结果"]
        for column, key, header in (
            (4, "u", "标准不确定度u(x)"),
            (5, "U", "扩展不确定度U(x)"),
            (6, "k", "包含因子k"),
        ):
            headers = [worksheet.cell(1, i).value for i in range(1, worksheet.max_column + 1)]
            aliases = getattr(book, "_openpt_columns", {}).get("参加者结果", {})
            label = aliases.get(header, header)
            if label in headers:
                if headers.count(label) != 1:
                    raise InputError(f"参加者结果!1 表头 {label!r} 不唯一")
                column = headers.index(label) + 1
            elif aliases or headers[:3] != SHEETS["参加者结果"]:
                continue
            cell = worksheet.cell(row[0].row, column)
            if cell.data_type == "f":
                raise InputError(f"参加者结果!{cell.coordinate}: 不接受公式")
            if cell.value is not None:
                participant[key] = _numeric(cell, "参加者结果")
                participant[key + "_source"] = f"参加者结果!{cell.coordinate}"
        values.append(participant)
    return values


def _claims(book: Any) -> list[dict[str, Any]]:
    """读取报告声称值及其来源。"""
    values = []
    for row in _rows(book, "报告声称值"):
        if row[0].value is None or row[1].value is None or not row[3].value:
            raise InputError(f"报告声称值!{row[0].row}: 项目、声称值及来源必填")
        values.append(
            {
                "name": str(row[0].value),
                "value": _numeric(row[1], "报告声称值"),
                "digits": row[2].value,
                "source": str(row[3].value),
                "model": row[4].value,
                "timegroup": row[5].value,
                "cell": f"报告声称值!{row[1].coordinate}",
            }
        )
    return values


def _batches(book: Any) -> list[dict[str, Any]]:
    """登记全部候选批次并校验状态、理由和批次关联；不做选择。"""
    if "候选批次" not in book.sheetnames:
        return []
    records = []
    seen: set[str] = set()
    for row in _rows(book, "候选批次"):
        if any(row[i].value in (None, "") for i in (0, 1, 2, 3, 4, 5, 7)):
            raise InputError(f"候选批次!{row[0].row}: 必填字段缺失")
        ident = str(row[0].value)
        if ident in seen:
            raise InputError(f"候选批次!{row[0].coordinate}: 批次编号重复")
        seen.add(ident)
        status = row[7].value
        if status not in ("候选", "失败", "选用", "弃用"):
            raise InputError(f"候选批次!{row[7].coordinate}: 状态无效")
        if status in ("失败", "弃用") and not str(row[8].value or "").strip():
            raise InputError(f"候选批次!{row[8].coordinate}: 失败或弃用须填写理由")
        record = {field: cell.value for field, cell in zip(SHEETS["候选批次"], row, strict=True)}
        raw = row[6].value
        if raw not in (None, ""):
            try:
                numbers = [float(item.strip()) for item in str(raw).split(",")]
                if not all(isfinite(item) for item in numbers):
                    raise ValueError("非有限数")
                record["预实验均值"] = statistics.mean(numbers)
                record["预实验标准差"] = statistics.stdev(numbers) if len(numbers) > 1 else None
            except (ValueError, OverflowError):
                raise InputError(
                    f"候选批次!{row[6].coordinate}: 预实验结果须为逗号分隔的有限数"
                ) from None
        records.append(record)
    for record in records:
        reference = record["关联批次"]
        if reference not in (None, "") and str(reference) not in seen:
            raise InputError(f"候选批次：关联批次 {reference} 不存在")
    return records


def read_workbook(
    path: str | Path,
    columns: dict[str, Any] | None = None,
    *,
    encoding: str = "utf-8-sig",
    csv_sheet: str = "均匀性",
    unit: str | None = None,
    project: str = "CSV 输入",
) -> dict[str, Any]:
    """读取 XLSX 或单测量表 CSV；CSV 单位必须由使用者明确登记。"""
    source = Path(path)
    if source.suffix.lower() == ".csv":
        if csv_sheet not in ("均匀性", "稳定性", "参加者结果") or not unit:
            raise InputError("CSV 导入须指定有效表类型和 --unit")
        try:
            with source.open("r", encoding=encoding, errors="strict", newline="") as stream:
                rows = list(csv.reader(stream))
        except (UnicodeDecodeError, LookupError) as exc:
            raise InputError("CSV 编码错误；GBK 文件请指定 --encoding gbk") from exc
        if not rows:
            raise InputError("CSV 缺少表头")
        book = Workbook()
        book.remove(book.active)
        for sheet, headers in SHEETS.items():
            book.create_sheet(sheet).append(headers)
        book["项目信息"].append(["项目名称", project])
        book["项目信息"].append(["单位", unit])
        ws = book[csv_sheet]
        ws.delete_rows(1)
        for row in rows:
            ws.append(row)
        aliases = (columns or {}).get(csv_sheet, {})
        if not isinstance(aliases, dict):
            raise InputError("CSV 列映射必须是对象")
        numeric_fields = ("值", *PARTICIPANT_OPTIONAL) if csv_sheet == "参加者结果" else ("值",)
        for field in numeric_fields:
            value_label = aliases.get(field, field)
            if rows[0].count(value_label) == 1:
                index = rows[0].index(value_label) + 1
                for row_number in range(2, ws.max_row + 1):
                    cell = ws.cell(row_number, index)
                    with suppress(ValueError, TypeError):
                        cell.value = float(cell.value) if cell.value not in (None, "") else None
        # CSV 是文本，不能将以等号开头的输入当作 Excel 公式。
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    cell.data_type = "s"
    elif source.suffix.lower() == ".xlsx":
        book = load_workbook(source, data_only=False)
    else:
        raise InputError("只支持 XLSX 或 CSV")
    if columns and set(columns) - set(SHEETS):
        raise InputError("列映射包含未知工作表")
    book._openpt_columns = columns or {}
    missing = set(SHEETS) - {"指定值与不确定度", "算法S", "候选批次"} - set(book.sheetnames)
    if missing:
        raise InputError("缺少工作表：" + ", ".join(sorted(missing)))
    info, config = _metadata(book)
    precision: list[int] = []
    hom, hs, hom_ids = _observations(book, "均匀性", info["单位"], precision)
    stab, ss, stab_ids = _observations(book, "稳定性", info["单位"], precision, True)
    assigned = {}
    if "指定值与不确定度" in book.sheetnames:
        assigned = {
            str(row[0].value): row[1].value
            for row in _rows(book, "指定值与不确定度")
            if row[0].value and row[1].value not in (None, "")
        }
        for key in ("independent", "hom_in_base", "stab_in_base", "trans_in_base", "trans_in_stab"):
            if assigned.get(key) in ("TRUE", "FALSE"):
                assigned[key] = assigned[key] == "TRUE"
    s_values: list[float] = []
    s_df = None
    if "算法S" in book.sheetnames:
        for row in _rows(book, "算法S"):
            value = _numeric(row[0], "算法S")
            df = _numeric(row[1], "算法S")
            if df != int(df) or (s_df is not None and df != s_df):
                raise InputError(f"算法S!{row[1].coordinate}: 自由度须为相同的整数")
            s_values.append(value)
            s_df = int(df)
    numeric_sources = {
        f"{ws.title}!{cell.coordinate}": cell.value
        for ws in book.worksheets
        if ws.title != "填写说明"
        for row in ws.iter_rows(min_row=2)
        for cell in row
        if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool)
    }
    return {
        "info": info,
        "numeric_sources": numeric_sources,
        "batches": _batches(book),
        "assigned_config": assigned,
        "algorithm_s_values": s_values,
        "algorithm_s_df": s_df,
        "config": config,
        "homogeneity": hom.get("均匀性", []),
        "homogeneity_units": hom_ids.get("均匀性", []),
        "stability": stab,
        "stability_units": stab_ids,
        "participants": _participants(book, info["单位"]),
        "claims": _claims(book),
        "sources": hs + ss,
        "data_decimal_places": max(precision) if precision else None,
    }
