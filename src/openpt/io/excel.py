# SPDX-License-Identifier: Apache-2.0
"""固定模板、输入校验及来源定位。"""

import csv
import re
import statistics
from collections import defaultdict
from collections.abc import Iterator
from contextlib import suppress
from decimal import Decimal
from io import BytesIO
from math import isfinite
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation

from ..errors import InputError
from .layout import wide_to_long
from .measurands import split_measurands
from .shape import STABILITY_METHOD_ALIASES, insufficient_homogeneity_replicates

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
    instructions.append(
        ["长表与宽表", "示例工作表仅供参考，不参与计算；复制相应表头到均匀性或稳定性表后填写数据。"]
    )
    for title, note in [
        ("项目信息", "必填：项目名称和单位。"),
        ("方法配置", "选填：需要修改默认方法或提供判据参数时填写。"),
        ("均匀性", "选填：需评价均匀性时填写；至少填写一张可计算的数据表。"),
        ("稳定性", "选填：需评价稳定性时填写；不填写则不会评价。"),
        ("参加者结果", "选填：需进行参加者评价或稳健统计时填写。"),
        ("报告声称值", "选填：需要复核报告数值时填写。"),
        ("指定值与不确定度", "选填：需要指定值建模和不确定度评定时填写。"),
        ("算法S", "选填：需要稳健联合标准差或极差时填写。"),
        ("候选批次", "选填：需要记录候选批次时填写。"),
        ("被测量配置", "选填：多个被测量分别登记单位、sigma 等；数据表和声称值的被测量列须对应。"),
        (
            "σ 与 σ_pt",
            "sigma 用于均匀性及稳定性判据；sigma_pt 是 z 等评价统计量的分母。"
            "只填一个时自动沿用，均填写时分别使用。",
        ),
    ]:
        instructions.append([title, note])
    instructions.column_dimensions["A"].width = 22
    instructions.column_dimensions["B"].width = 80
    for name, headers in SHEETS.items():
        ws = book.create_sheet(name)
        ws.append(headers)
        ws.cell(1, 1).comment = Comment("请按填写说明输入数据；不要输入 Excel 公式。", "OpenPT")
        ws.freeze_panes = "A2"
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = 22
    examples = {
        "示例-均匀性长表": (
            ["单元编号", "重复编号", "值", "单位"],
            [["A", 1, 1.0, "mg"], ["A", 2, 1.1, "mg"]],
        ),
        "示例-均匀性宽表": (["单元编号", "测定1", "测定2", "单位"], [["A", 1.0, 1.1, "mg"]]),
        "示例-稳定性长表": (
            ["时间组", "单元编号", "重复编号", "值", "单位"],
            [["稳定期", "A", 1, 1.0, "mg"], ["稳定期", "A", 2, 1.1, "mg"]],
        ),
        "示例-稳定性宽表": (
            ["时间组", "单元编号", "测定1", "测定2", "单位"],
            [["稳定期", "A", 1.0, 1.1, "mg"]],
        ),
    }
    for name, (headers, example_rows) in examples.items():
        ws = book.create_sheet(name)
        ws.append(headers)
        for example_row in example_rows:
            ws.append(example_row)
        ws.cell(1, 1).comment = Comment("示例不参与计算，请复制表头和数据到正式工作表。", "OpenPT")
    for col, header in enumerate(("标准不确定度u(x)", "扩展不确定度U(x)", "包含因子k"), 4):
        book["参加者结果"].cell(1, col, header)
    for name in ("均匀性", "稳定性", "报告声称值"):
        ws = book[name]
        ws.cell(1, ws.max_column + 1, "被测量")
    options_sheet = book.create_sheet("被测量配置")
    options_sheet.append(["被测量", "字段", "值", "（选填）"])
    for name in set(SHEETS) - {"项目信息"}:
        ws = book[name]
        ws.cell(1, ws.max_column + 1, "（选填）")
    for row in [("项目名称", ""), ("单位", "")]:
        book["项目信息"].append(row)
    for config_row in [
        ("显著性水平（alpha）", 0.05),
        ("均匀性/稳定性判据标准差（sigma）", ""),
        ("严格均匀性配置（strict_homogeneity）", False),
        ("稳定性方法（stability_method）", "two_sample"),
        ("单均值参考值（reference）", ""),
        ("指定值（assigned）", ""),
        ("z等评价标准差（sigma_pt）", ""),
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
        ("最大允许偏差（delta_e）", ""),
        ("GB/T 判据依据（gbt_criterion_basis）", ""),
        ("稳定性均值基线来源（baseline_source）", ""),
        ("报告声明的稳定性方法（report_stability_method）", ""),
        ("重复性质（replicate_type）", "technical"),
        ("测量表布局（layout）", ""),
    ]:
        book["方法配置"].append(config_row)
    for cell, options in [
        ("B4", '"启用,关闭"'),
        ("B5", '"两均值,单均值,均值差法（GL003 5.3）"'),
        ("B9", '"gl002,gbt28043,absolute,simplified"'),
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
        ("B29", '"sigma_pt,delta_e"'),
        ("B30", '"homogeneity,baseline_group"'),
        ("B31", '"one_sample,two_sample,mean_difference"'),
        ("B32", '"technical,adjacent_specimens,other,single"'),
        ("B33", '"long,wide"'),
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
        ("stability_disposition", "pending"),
        ("stability_disposition_reason", ""),
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
        ("B27", '"pending,budgeted,reviewed,withhold"'),
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
        if key == "stability_method" and value in STABILITY_METHOD_ALIASES:
            value = STABILITY_METHOD_ALIASES[value]
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
    book: Any,
    name: str,
    unit: str,
    precision: list[int],
    stability: bool = False,
    replicate_type: str = "technical",
    layout: str | None = None,
) -> tuple[dict[str, Any], list[str], dict[str, list[str]]]:
    """读取包装单元和重复测量，记录单元格位置。"""
    grouped: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    unit_sources: dict[tuple[str, str], str] = {}
    sources = []
    ws = book[name]
    raw_rows = [list(row) for row in ws.iter_rows(values_only=True)]
    aliases = getattr(book, "_openpt_columns", {})
    wide = wide_to_long(name, raw_rows, aliases, layout)
    records = []
    if wide is not None:
        normalized, origins = wide
        for index, record_values in enumerate(normalized[1:], 2):
            group, uid, rep, _number, actual_unit = (
                (
                    record_values[0],
                    record_values[1],
                    record_values[2],
                    record_values[3],
                    record_values[4],
                )
                if stability
                else (
                    "均匀性",
                    record_values[0],
                    record_values[1],
                    record_values[2],
                    record_values[3],
                )
            )
            value_column = "D" if stability else "C"
            unit_column = "E" if stability else "D"
            value_address = origins[f"{value_column}{index}"]
            unit_address = origins[f"{unit_column}{index}"]
            val = ws[value_address]
            for column in "ABCDE" if stability else "ABCD":
                address = origins[f"{column}{index}"]
                if ws[address].data_type == "f":
                    raise InputError(f"{name}!{address}: 不接受公式")
            records.append((group, uid, rep, val, actual_unit, unit_address))
    else:
        for row in _rows(book, name):
            group, uid, rep, val, actual_unit = (
                (row[0].value, row[1].value, row[2].value, row[3], row[4].value)
                if stability
                else ("均匀性", row[0].value, row[1].value, row[2], row[3].value)
            )
            records.append((group, uid, rep, val, actual_unit, row[-1].coordinate))
    for group, uid, rep, val, actual_unit, unit_address in records:
        if not group or uid is None or rep is None:
            raise InputError(f"{name}!{val.row}: 缺少分组或编号")
        if actual_unit != unit:
            raise InputError(f"{name}!{unit_address}: 单位不一致")
        key, repeat = (str(group), str(uid)), str(rep)
        if repeat in grouped[key]:
            raise InputError(f"{name}!{val.coordinate}: 重复编号")
        grouped[key][repeat] = _numeric(val, name)
        unit_sources[key] = f"{name}!{val.coordinate}"
        precision.append(_precision(val))
        sources.append(f"{name}!{val.coordinate}")
    groups: dict[str, list[list[float]]] = defaultdict(list)
    unit_ids: dict[str, list[str]] = defaultdict(list)
    for (group, uid), values in grouped.items():
        if not stability and replicate_type == "single" and len(values) != 1:
            raise InputError(f"{unit_sources[(group, uid)]}: 单测设计每单元须恰好测量一次")
        if (
            not stability
            and replicate_type != "single"
            and insufficient_homogeneity_replicates(len(values))
        ):
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
    path: str | Path | BytesIO,
    columns: dict[str, Any] | None = None,
    *,
    encoding: str = "utf-8-sig",
    csv_sheet: str = "均匀性",
    unit: str | None = None,
    project: str = "CSV 输入",
) -> dict[str, Any]:
    """读取 XLSX 或单测量表 CSV；CSV 单位必须由使用者明确登记。"""
    source = path if isinstance(path, BytesIO) else Path(path)
    suffix = ".xlsx" if isinstance(source, BytesIO) else source.suffix.lower()
    if suffix == ".csv" and isinstance(source, Path):
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
        numeric_fields: tuple[str, ...] = (
            ("值", *PARTICIPANT_OPTIONAL) if csv_sheet == "参加者结果" else ("值",)
        )
        numeric_fields += tuple(
            field for field in rows[0] if re.fullmatch(r"测定\s*[1-9][0-9]*", field)
        )
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
    elif suffix == ".xlsx":
        if isinstance(source, BytesIO):
            source.seek(0)
        book = load_workbook(source, data_only=False)
    else:
        raise InputError("只支持 XLSX 或 CSV")
    if columns and set(columns) - set(SHEETS):
        raise InputError("列映射包含未知工作表")
    book._openpt_columns = columns or {}
    if "项目信息" not in book.sheetnames:
        raise InputError("缺少工作表：项目信息")
    for sheet, headers in SHEETS.items():
        if sheet not in book.sheetnames:
            book.create_sheet(sheet).append(headers)
    info, config = _metadata(book)
    separated = split_measurands(book, columns)
    if separated:
        if suffix == ".csv":
            raise InputError("CSV 多被测量输入不支持，请使用 XLSX")
        subdata = {}
        for item in separated:
            part = read_workbook(BytesIO(item["bytes"]), columns)
            for virtual, original in item["sources"].items():
                if virtual in part["numeric_sources"]:
                    part["numeric_sources"][original] = part["numeric_sources"].pop(virtual)
            part["measurand_overrides"] = {
                key: value for key, value in part["config"].items() if config.get(key) != value
            }
            subdata[item["name"]] = part
        first = next(iter(subdata.values()))
        return {**first, "info": info, "config": config, "measurands": subdata}
    precision: list[int] = []
    replicate_type = config.get("replicate_type") or "technical"
    if replicate_type not in ("technical", "adjacent_specimens", "other", "single"):
        raise InputError("replicate_type 应为 technical、adjacent_specimens、other 或 single")
    layout = config.get("layout") or None
    hom, hs, hom_ids = _observations(
        book, "均匀性", info["单位"], precision, replicate_type=replicate_type, layout=layout
    )
    stab, ss, stab_ids = _observations(book, "稳定性", info["单位"], precision, True, layout=layout)
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
        if ws.title != "填写说明" and not ws.title.startswith("示例-")
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
