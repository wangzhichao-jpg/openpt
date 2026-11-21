# SPDX-License-Identifier: Apache-2.0
"""Windows 单窗口入口，计算仍由运行快照管线完成。"""

from __future__ import annotations

import os
import queue
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from openpyxl import load_workbook

from .errors import format_error
from .formatting import display_value
from .io.period_table import create_period_sheet
from .report.period_criteria import has_period_overrides, period_fields, selected_periods
from .runs import create_run


def example_path() -> Path:
    """定位打包资源或源码中的示例。"""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / "windows" / "甲醛示例.xlsx"


def make_template(target: Path) -> None:
    """从示例生成不含测量结果的模板。"""
    if target.resolve() == example_path().resolve():
        raise ValueError("不能覆盖示例文件")
    book = load_workbook(example_path())
    create_period_sheet(book)
    book["项目信息"]["B2"] = None
    book["项目信息"]["B3"] = None
    if not any(
        "（display_value_decimals）" in str(row[0].value)
        for row in book["方法配置"].iter_rows(min_row=2)
    ):
        book["方法配置"].append(["量值显示小数位（display_value_decimals）", None])
    for label, field in (
        ("分位数算法", "quantile_method"),
        ("判据标准差来源", "criterion_sigma_source"),
        ("算法S输入类型", "algorithm_s_input_type"),
    ):
        if not any(
            f"（{field}）" in str(row[0].value) for row in book["方法配置"].iter_rows(min_row=2)
        ):
            book["方法配置"].append([f"{label}（{field}）", None])
    for field in ("sigma_pt_method", "sigma_pt_sig_digits"):
        if not any(row[0].value == field for row in book["指定值与不确定度"].iter_rows(min_row=2)):
            book["指定值与不确定度"].append([field, None])
    for row in book["方法配置"].iter_rows(min_row=2):
        if row[0].value and any(
            key in str(row[0].value) for key in ("（sigma）", "（sigma_source）", "（sigma_stage）")
        ):
            row[1].value = None
    for row in book["指定值与不确定度"].iter_rows(min_row=2):
        if row[0].value in (
            "source",
            "uncertainty_source",
            "sigma_final",
            "sigma_procedure",
            "u_hom",
            "u_stab",
        ):
            row[1].value = None
        elif row[0].value in ("hom_mapping", "stab_mapping"):
            row[1].value = "none"
    for name in ("均匀性", "稳定性", "参加者结果"):
        sheet = book[name]
        if sheet.max_row > 1:
            sheet.delete_rows(2, sheet.max_row - 1)
    book.save(target)


def run_workbook(source: Path, root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """使用同一输入验证和运行目录管线，不修改源工作簿。"""
    args = SimpleNamespace(
        input=str(source),
        command="run",
        columns=None,
        mapping=None,
        sample_record=None,
        encoding="utf-8-sig",
        csv_sheet=None,
        unit=None,
        project=None,
    )
    directory, data, result, _, _ = create_run(args, root)
    return directory, data, result


def _decision(value: Any) -> str:
    return "通过" if value is True else "未通过" if value is False else "未计算"


def summarize(data: dict[str, Any], result: dict[str, Any]) -> str:
    """按选定方法展示结果；缺失项目不阻断其他项目。"""
    if result.get("被测量"):
        return "\n\n".join(
            f"被测量：{name}\n{summarize(data.get('measurands', {}).get(name, data), part)}"
            for name, part in result["被测量"].items()
        )
    unit = data.get("info", {}).get("单位", "")
    cfg = data.get("config", {})
    sig = int(cfg.get("display_sig_digits") or 4)
    raw_places = cfg.get("display_value_decimals")
    places = int(raw_places) if raw_places not in (None, "") else None
    z_places = (
        int(cfg["display_z_decimals"]) if cfg.get("display_z_decimals") not in (None, "") else 2
    )

    def value_text(value: Any) -> str:
        return display_value(value, sig, places)

    def _number(value: Any) -> str:
        return display_value(value, sig)

    lines = []
    if result.get("诊断提示"):
        lines.extend(["【诊断提示】", *(item["说明"] for item in result["诊断提示"]), ""])
    lines.extend([f"项目：{data.get('info', {}).get('项目名称', '')}　单位：{unit}", ""])
    hom = result.get("均匀性")
    gbt_hom = result.get("GB/T均匀性")
    transfer = result.get("传递标准稳定性") or {}
    if gbt_hom:
        rule = gbt_hom.get("selected_rule", "basic")
        clause = "B.1.2" if gbt_hom.get("m") == 1 else "B.2.3" if rule == "extended" else "B.2.2"
        lines.append(
            f"均匀性（GB/T 28043 {clause}）：Ss = {_number(gbt_hom.get('ss'))}；"
            f"限值 = {_number(gbt_hom.get(rule + '_limit'))}；"
            f"{_decision(gbt_hom.get('conclusion'))}"
        )
    elif hom:
        hom_method = {
            "ss_0.3sigma": "GL003 4.3",
            "f_test": "GL003 4.2 F检验",
            "both": "GL003 4.2及4.3",
        }.get(hom.get("selected_criterion"), hom.get("selected_criterion", "工作簿所选方法"))
        lines.append(f"均匀性（{hom_method}）")
        lines.append(
            f"  Ss = {_number(hom.get('Ss'))}；限值 = {_number(hom.get('threshold'))}；"
            f"{_decision(hom.get('conclusion'))}"
        )
        if hom.get("F") is not None:
            lines.append(
                f"  F = {_number(hom.get('F'))}；F 临界值 = {_number(hom.get('F_critical'))}"
            )
    else:
        standards = {point.get("standard") for point in transfer.values()}
        lines.append(
            "单台传递标准：不适用样品间均匀性检验"
            if len(standards) == 1 and None not in standards
            else "均匀性：未计算"
        )
    lines.append("")
    stability = result.get("稳定性")
    groups = {result.get("稳定性时间组", "稳定期"): stability} if stability else {}
    groups.update(result.get("其他稳定性") or {})
    gbt_groups = result.get("GB/T稳定性") or {}
    _, selected_groups = selected_periods(result)
    show_criteria = has_period_overrides(selected_groups)

    def criteria_suffix(item: dict[str, Any], gbt: bool) -> str:
        if not show_criteria:
            return ""
        fields = period_fields(item, gbt, sig)
        delta = f"；δE={fields['delta_e']}" if gbt and fields["basis"].startswith("δE") else ""
        return (
            f"；方法={fields['method']}；判据={fields['rule']}；"
            f"依据={fields['basis']}{delta}；基线={fields['baseline_source']}"
        )

    if gbt_groups:
        groups = {}
        for name, item in gbt_groups.items():
            rule = item.get("selected_rule", "basic")
            clause = "B.5.2" if rule == "extended" else "B.5.1"
            lines.append(
                f"{name}（GB/T 28043 {clause}）：差值 = {_number(item.get('difference'))}；"
                f"限值 = {_number(item.get(rule + '_limit'))}；{_decision(item.get('conclusion'))}"
                f"{criteria_suffix(item, True)}"
            )
    if not groups and not gbt_groups and not transfer:
        lines.append("稳定性：未计算")
    for name, item in groups.items():
        mean_difference = item.get("method") == "mean_difference"
        statistic = item.get("difference") if mean_difference else item.get("t")
        limit = item.get("threshold") if mean_difference else item.get("critical")
        label = "差值" if mean_difference else "t"
        conclusion = item.get("mean_difference_pass") if mean_difference else item.get("pass")
        method_name = "GL003 5.3 均值差" if mean_difference else item.get("method", "")
        lines.append(
            f"{name}（{method_name}）：{label} = {_number(statistic)}；"
            f"限值 = {_number(limit)}；{_decision(conclusion)}{criteria_suffix(item, False)}"
        )
    for name, point in transfer.items():
        lines.append(
            f"传递标准 {name}：Δmax = {_number(point.get('delta_max'))} {point.get('unit', '')}"
        )
        for criterion in point.get("criteria", []):
            lines.append(
                f"  {criterion.get('kind', '')}：统计量 = {_number(criterion.get('value'))}；"
                f"限值 = {_number(criterion.get('limit'))}；{_decision(criterion.get('pass'))}"
            )
    assigned = result.get("指定值与不确定度")
    lines.append("")
    if assigned:
        method = assigned.get("method", "")
        method = {"reference": "参考测量", "certified": "有证参考值"}.get(method, method)
        if method == "participant_consensus":
            method = (
                "算法A稳健公议"
                if assigned.get("consensus_method") == "robust_mean"
                else "参加者公议 / " + str(assigned.get("consensus_method", ""))
            )
        lines.append(
            f"指定值（{method}）：X = {value_text(assigned.get('value'))}；"
            f"u = {value_text(assigned.get('u'))} {unit}"
        )
        if (
            assigned.get("method") == "participant_consensus"
            and assigned.get("consensus_method") == "robust_mean"
            and result.get("算法A")
        ):
            algorithm = result["算法A"]
            rule = {
                "gl002": "GL002 停止规则",
                "gbt28043": "GB/T 28043 停止规则",
                "absolute": "绝对容差停止规则",
                "simplified": "简化法",
            }.get(algorithm.get("rule"), str(algorithm.get("rule")))
            lines.append(f"算法A：迭代 {algorithm['iterations']} 次（{rule}）")
        if places is None:
            lines.append("可在『方法配置』display_value_decimals 设置指定值、σ_pt 及结果值的小数位")
    elif cfg.get("assigned") not in (None, ""):
        lines.append(f"指定值（方法配置）：X = {value_text(cfg['assigned'])} {unit}；u = 未计算")
    else:
        lines.append("指定值：未计算")
    if (
        assigned
        or result.get("参加者z")
        or any(cfg.get(key) not in (None, "") for key in ("sigma_pt", "sigma"))
    ):
        assigned = assigned or {}
        sigma = assigned.get("sigma_final")
        source = "sigma_final"
        if sigma is None:
            sigma = assigned.get("sigma_temporary")
            source = "sigma_temporary"
        if sigma is None:
            sigma = cfg.get("sigma_pt")
            source = "方法配置 sigma_pt"
            if assigned:
                source += "；未用于指定值表的参加者统计量"
        if sigma is None and cfg.get("sigma") is not None:
            sigma, source = cfg["sigma"], "方法配置 sigma（沿用）"
            if assigned:
                source += "；未用于指定值表的参加者统计量"
        source_label = source if sigma is not None else "未提供"
        sigma_info = result.get("σ_pt确定")
        if sigma_info:
            source_label = sigma_info["procedure"]
        shown_sigma = (
            display_value(sigma, sigma_info["sig_digits"])
            if sigma_info
            and sigma_info.get("sig_digits")
            and sigma_info["sig_digits"] <= 15
            and places is None
            else value_text(sigma)
        )
        lines.append(f"σ_pt = {shown_sigma} {unit}（来源：{source_label}）")
        prime = assigned.get("sigma_prime")
        if prime is not None and (
            prime != sigma
            or any(assigned.get(k) == "sigma_prime" for k in ("hom_mapping", "stab_mapping"))
        ):
            suffix = (
                "（与 σ_pt 的差异小于显示精度）"
                if prime != sigma and value_text(prime) == value_text(sigma)
                else "（含分量映射）"
            )
            lines.append(f"σ′ = {value_text(prime)} {unit}{suffix}")
    scores = result.get("参加者统计量")
    if scores is None and result.get("参加者z"):
        scores = {
            participant: {"z": {**score, "value": score.get("z")}}
            for participant, score in result["参加者z"].items()
        }
    if scores is not None:
        lines.extend(["", "【参加者统计量】"])
        warnings: set[str] = set()
        participants = {str(p["id"]): p for p in data.get("participants", [])}
        for participant, statistics in scores.items():
            p = participants.get(str(participant), {})
            for name, score in statistics.items():
                classification = score.get("classification") or "未评价"
                reason = score.get("reason")
                if reason:
                    classification += f"（{reason}）"
                number = score.get("value")
                shown = display_value(number, places=z_places) if number is not None else "未计算"
                lines.append(
                    f"{participant} | 结果值 {value_text(p.get('value'))} | "
                    f"{name} = {shown} | {classification}"
                )
                warnings.update(score.get("warnings") or [])
        for warning in sorted(warnings):
            lines.append("提示：" + warning)
    return "\n".join(lines)


def result_text_content(text: str, directory: Path | None = None) -> str:
    """生成结果区内容；失败时完整保留问题清单。"""
    return text + "\n\n结果目录：" + str(directory) if directory is not None else text


def error_dialog_summary(text: str, limit: int = 4) -> str:
    """弹窗只展示摘要，完整内容留在结果区。"""
    lines = text.splitlines()
    if len(lines) > limit:
        return "\n".join(lines[:limit]) + "\n……完整清单见结果区。"
    if len(text) > 500:
        return text[:500] + "……完整清单见结果区。"
    return text


def friendly_error(exc: Exception) -> str:
    """将输入检查结果简化为表名、单元格和问题。"""
    return format_error(exc)


def main() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("能力验证样品评价与定值工具")
    root.geometry("800x530")
    selected = tk.StringVar(value="请选择数据文件")
    output: list[Path] = []
    events: queue.Queue[tuple[str, Any]] = queue.Queue()
    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="能力验证样品评价与定值工具", font=("Microsoft YaHei", 16)).pack(
        anchor="w"
    )
    ttk.Label(frame, textvariable=selected, wraplength=740).pack(anchor="w", pady=12)
    buttons = ttk.Frame(frame)
    buttons.pack(anchor="w")
    result_frame = ttk.Frame(frame)
    result_frame.pack(fill="both", expand=True, pady=15)
    scrollbar = ttk.Scrollbar(result_frame, orient="vertical")
    scrollbar.pack(side="right", fill="y")
    result_text = tk.Text(
        result_frame,
        height=17,
        wrap="word",
        font=("Microsoft YaHei", 10),
        yscrollcommand=scrollbar.set,
    )
    result_text.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=result_text.yview)
    status = tk.StringVar(value="载入示例或选择数据文件。")
    ttk.Label(frame, textvariable=status).pack(anchor="w")

    def pick() -> None:
        path = filedialog.askopenfilename(filetypes=[("Excel 工作簿", "*.xlsx")])
        if path:
            selected.set(path)

    def template() -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx", filetypes=[("Excel 工作簿", "*.xlsx")]
        )
        if path:
            try:
                make_template(Path(path))
                selected.set(path)
                status.set("模板已创建，请填写并保存后计算。")
            except Exception:
                messagebox.showerror("创建模板", "无法创建模板，请检查文件是否被占用。")

    def worker(source: Path) -> None:
        try:
            directory, data, result = run_workbook(source, Path.home() / "Documents" / "OpenPT结果")
            events.put(("ok", (directory, summarize(data, result))))
        except (ValueError, OSError, KeyError) as exc:
            events.put(("error", friendly_error(exc)))
        except Exception:
            events.put(("error", "无法读取或计算该工作簿，请检查工作表及数据格式。"))

    def calculate() -> None:
        source = Path(selected.get())
        if not source.is_file():
            messagebox.showerror("选择文件", "请先载入示例或选择 Excel 文件。")
            return
        start_button.config(state="disabled")
        status.set("正在计算，请稍候……")
        threading.Thread(target=worker, args=(source,), daemon=True).start()

    def poll() -> None:
        try:
            kind, value = events.get_nowait()
        except queue.Empty:
            root.after(100, poll)
            return
        start_button.config(state="normal")
        if kind == "ok":
            directory, text = value
            output[:] = [directory]
            result_text.delete("1.0", "end")
            result_text.insert("1.0", result_text_content(text, directory))
            status.set("计算完成。")
        else:
            output.clear()
            result_text.delete("1.0", "end")
            result_text.insert("1.0", result_text_content(str(value)))
            status.set("计算未完成。")
            messagebox.showerror("输入或计算问题", error_dialog_summary(str(value)))
        root.after(100, poll)

    def open_output(report: bool) -> None:
        if not output:
            messagebox.showinfo("结果", "请先完成计算。")
            return
        path = output[0] / "report.docx" if report else output[0]
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError:
            messagebox.showerror("打开结果", "无法打开结果，请检查关联程序。")

    ttk.Button(
        buttons, text="载入甲醛示例", command=lambda: selected.set(str(example_path()))
    ).pack(side="left", padx=3)
    ttk.Button(buttons, text="新建数据模板", command=template).pack(side="left", padx=3)
    ttk.Button(buttons, text="选择数据文件", command=pick).pack(side="left", padx=3)
    start_button = ttk.Button(buttons, text="开始计算", command=calculate)
    start_button.pack(side="left", padx=3)
    ttk.Button(buttons, text="打开计算书", command=lambda: open_output(True)).pack(
        side="left", padx=3
    )
    ttk.Button(buttons, text="打开结果目录", command=lambda: open_output(False)).pack(
        side="left", padx=3
    )
    smoke_dir = os.environ.get("OPENPT_GUI_SMOKE_DIR")
    if smoke_dir:
        # 冒烟测试必须先实际创建、显示窗口，再经过同一业务适配层。
        root.update_idletasks()
        root.update()
        smoke_source = os.environ.get("OPENPT_GUI_SMOKE_SOURCE")
        source = Path(smoke_source) if smoke_source else example_path()
        directory, data, result = run_workbook(source, Path(smoke_dir))
        (Path(smoke_dir) / "gui-smoke.txt").write_text(
            summarize(data, result) + "\n" + str(directory), encoding="utf-8"
        )
        root.destroy()
        return
    root.after(100, poll)
    root.mainloop()
