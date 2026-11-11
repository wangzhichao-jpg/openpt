# SPDX-License-Identifier: Apache-2.0
"""命令行入口。"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from . import __version__
from .core.assigned import assign_value
from .core.homogeneity import analyze as homogeneity
from .core.robust import algorithm_a, algorithm_s, median_niqr
from .core.scores import performance_score
from .core.stability import analyze as stability
from .core.zscore import zscore
from .io.excel import read_workbook, template
from .report.docx import make_report


def _option(config: dict[str, Any], key: str, default: Any) -> Any:
    value = config.get(key)
    return default if value in (None, "") else value


def _participant_results(data: dict[str, Any], sigma: float | None) -> dict[str, Any]:
    """计算 GL002 附录 A.2 算法 A 及 GL002 4.4 的 z。"""
    cfg = data["config"]
    simplified = _option(cfg, "algorithm_a_simplified", False)
    if not isinstance(simplified, bool):
        raise ValueError("algorithm_a_simplified 必须是布尔值")
    values = [p["value"] for p in data["participants"]]
    result: dict[str, Any] = {}
    if len(values) >= 2:
        result["算法A"] = algorithm_a(
            values,
            tolerance=float(_option(cfg, "algorithm_a_tolerance", 1e-10)),
            max_iterations=int(_option(cfg, "algorithm_a_max_iterations", 1000)),
            simplified=simplified,
            rule=str(_option(cfg, "algorithm_a_rule", "gl002")),
        ).to_dict()
        result["中位数NIQR"] = median_niqr(values).to_dict()
        # 绝对容差对照独立于选定停止规则，供附录和敏感性提示使用。
        result["算法A_收敛对照"] = algorithm_a(
            values, rule="absolute", tolerance=1e-12, max_iterations=10000
        ).to_dict()
    else:
        result["稳健统计状态"] = "NOT_EVALUATED：至少需要两个参加者结果"
    sigma_pt = float(cfg["sigma_pt"]) if cfg.get("sigma_pt") not in (None, "") else sigma
    if (
        cfg.get("assigned") not in (None, "")
        and sigma_pt is not None
        and not data.get("assigned_config", {}).get("method")
    ):
        result["参加者z"] = {
            p["id"]: zscore(
                p["value"],
                float(cfg["assigned"]),
                sigma_pt,
                float(_option(cfg, "z_satisfactory", 2)),
                float(_option(cfg, "z_unsatisfactory", 3)),
            ).to_dict()
            for p in data["participants"]
        }
    return result


def _assigned_results(data: dict[str, Any]) -> dict[str, Any]:
    """执行指定值建模和 GL002 4.4.1.3 选定统计量。"""
    a = data.get("assigned_config", {})
    keys = (
        "value",
        "uncertainty",
        "source",
        "uncertainty_source",
        "consensus_method",
        "sigma_temporary",
        "sigma_final",
        "sigma_procedure",
        "u_hom",
        "u_stab",
        "hom_mapping",
        "stab_mapping",
        "hom_in_base",
        "stab_in_base",
    )
    options = {key: a[key] for key in keys if key in a}
    assigned = assign_value(
        a["method"], participants=[p["value"] for p in data["participants"]], **options
    )
    result: dict[str, Any] = {"指定值与不确定度": assigned.to_dict()}
    kind = _option(data["config"], "score_type", "z")
    if kind not in ("z", "zprime", "zeta", "En", "D", "D%", "all"):
        raise ValueError("未知统计量类型")
    kinds = ("D", "D%", "z", "zprime", "zeta", "En") if kind == "all" else (kind,)
    participant_scores: dict[str, Any] = {}
    for participant in data["participants"]:
        scores = {}
        for name in kinds:
            if assigned.status != "OK" or assigned.value is None:
                scores[name] = {
                    "statistic": name,
                    "value": None,
                    "status": assigned.status,
                    "classification": None,
                    "reason": "指定值或分量映射未通过审核",
                    "formula": "GL002 4.4.1.3",
                    "warnings": assigned.warnings,
                }
            else:
                score_result = performance_score(
                    name,
                    participant["value"],
                    assigned.value,
                    sigma=assigned.sigma_prime,
                    sigma_pt_reference=assigned.sigma_final
                    if assigned.sigma_final is not None
                    else assigned.sigma_temporary,
                    u_assigned=assigned.u,
                    u_participant=participant.get("u"),
                    U_assigned=a.get("U_assigned"),
                    U_participant=participant.get("U"),
                    k_assigned=a.get("k_assigned"),
                    k_participant=participant.get("k"),
                    independent=a.get("independent"),
                    assigned_from_participants=assigned.method == "participant_consensus",
                    satisfactory=float(_option(data["config"], "z_satisfactory", 2)),
                    unsatisfactory=float(_option(data["config"], "z_unsatisfactory", 3)),
                    en_limit=float(_option(data["config"], "en_limit", 1)),
                )
                if assigned.sigma_final is None and assigned.sigma_temporary is not None:
                    score_result.warnings.append("能力评定标准差为临时值，评价仅供暂时参考")
                scores[name] = score_result.to_dict()
        participant_scores[participant["id"]] = scores
    result["参加者统计量"] = participant_scores
    return result


def calculate(data: dict[str, Any]) -> dict[str, Any]:
    """根据输入选择 GL003 与 GL002 计算方法。"""
    cfg = data["config"]
    alpha = float(_option(cfg, "alpha", 0.05))
    raw = cfg.get("sigma")
    sigma = float(raw) if raw not in (None, "") else None
    if cfg.get("gbt28043_extension"):
        raise ValueError("GB/T 28043 扩展配置尚未实现")
    result = {}
    if data["homogeneity"]:
        strict = cfg.get("strict_homogeneity", False)
        if not isinstance(strict, bool):
            raise ValueError("strict_homogeneity 必须是布尔值")
        result["均匀性"] = homogeneity(
            data["homogeneity"],
            sigma,
            alpha,
            strict,
            _option(cfg, "sigma_source", None),
            _option(cfg, "sigma_stage", None),
        ).to_dict()
    groups = data["stability"]
    method = cfg.get("stability_method") or "two_sample"
    if groups:
        if "稳定期" not in groups or (method == "two_sample" and "基线" not in groups):
            raise ValueError("稳定性须指定基线及稳定期组")
        raw = cfg.get("reference")
        reference = float(raw) if raw not in (None, "") else None
        level = _option(cfg, "observation_level", "unit_means")
        if level not in ("unit_means", "all_repeats"):
            raise ValueError("未知实验层级")
        if level == "all_repeats":
            raise ValueError("全部重复值仅供复核模型使用，不可用于常规结论")
        design_options = {
            "design": _option(cfg, "stability_design", "independent"),
            "reference_uncertainty_negligible": _option(
                cfg, "reference_uncertainty_negligible", True
            ),
            "reference_source": _option(cfg, "reference_source", None),
        }
        result["稳定性"] = stability(
            groups.get("基线"),
            groups["稳定期"],
            sigma,
            alpha,
            method,
            reference,
            **design_options,
        ).to_dict()
        extra = {}
        for name, observations in groups.items():
            if name not in ("基线", "稳定期"):
                extra[name] = stability(
                    groups.get("基线"),
                    observations,
                    sigma,
                    alpha,
                    method,
                    reference,
                    group_name=name,
                    **design_options,
                ).to_dict()
        if extra:
            result["其他稳定性"] = extra
    if data["participants"]:
        result.update(_participant_results(data, sigma))
    if data.get("assigned_config", {}).get("method"):
        result.update(_assigned_results(data))
    if data.get("algorithm_s_values"):
        result["算法S"] = algorithm_s(data["algorithm_s_values"], data["algorithm_s_df"]).to_dict()
    if not result:
        raise ValueError("没有可计算的数据")
    return result


def _parser() -> argparse.ArgumentParser:
    """创建带中文说明的命令行参数。"""
    parser = argparse.ArgumentParser(prog="openpt", description="能力验证统计工作台")
    parser.add_argument(
        "--version", action="version", version=f"openpt {__version__}", help="显示版本"
    )
    sub = parser.add_subparsers(dest="command", required=True, title="命令")
    t = sub.add_parser("template", help="生成空白 Excel 模板")
    t.add_argument("output", help="模板文件路径")
    demo = sub.add_parser("demo", help="生成公开演示数据及计算结果")
    demo.add_argument("directory", help="示例输出目录")
    batch = sub.add_parser("review-batch", help="批量复核并输出 XLSX 差异总表")
    batch.add_argument("inputs", nargs="+", help="输入 Excel 文件")
    batch.add_argument("--output", required=True, help="差异总表 XLSX 路径")
    batch.add_argument("--mapping", help="可选 JSON 评分映射")
    for name in ("run", "review"):
        p = sub.add_parser(name, help="运行计算" if name == "run" else "复核报告")
        p.add_argument("input", help="输入 Excel 文件")
        p.add_argument("--docx", help="计算书路径；默认写入输入文件旁")
        p.add_argument("--json", help="结果 JSON 路径；默认写入输入文件旁")
        if name == "review":
            p.add_argument("--differences", help="差异 CSV 路径；默认写入输入文件旁")
            p.add_argument("--mapping", help="可选 JSON 评分映射")
    return parser


def _validate_output_paths(args: argparse.Namespace) -> None:
    """防止输出文件覆盖输入、映射文件或彼此覆盖。"""
    outputs = [Path(args.docx).resolve(), Path(args.json).resolve()]
    protected = {Path(args.input).resolve()}
    if args.command == "review":
        outputs.append(Path(args.differences).resolve())
        if args.mapping:
            protected.add(Path(args.mapping).resolve())
    if len(set(outputs)) != len(outputs) or protected.intersection(outputs):
        raise ValueError("输出路径不得覆盖输入文件、映射文件或其他输出文件")


def _configure_console() -> None:
    """控制台不支持中文时替换字符，重定向输出采用 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            if stream.isatty():
                reconfigure(errors="replace")
            else:
                reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # 嵌入式或测试捕获流可能不支持重新配置。
            continue


def main(argv: list[str] | None = None) -> int:
    """执行模板、计算或复核命令，返回进程退出码。"""
    _configure_console()
    args = _parser().parse_args(argv)
    try:
        if args.command == "template":
            template(args.output)
            return 0
        if args.command == "demo":
            from .demo import create_demo

            create_demo(Path(args.directory))
            return 0
        if args.command == "review-batch":
            from .review.batch import batch_review, write_xlsx

            protected = {Path(path).resolve() for path in args.inputs}
            if args.mapping:
                protected.add(Path(args.mapping).resolve())
            if Path(args.output).resolve() in protected:
                raise ValueError("输出路径不得覆盖输入或映射")
            mapping = (
                json.loads(Path(args.mapping).read_text(encoding="utf-8")) if args.mapping else None
            )
            if mapping is not None and not isinstance(mapping, dict):
                raise ValueError("评分映射必须是 JSON 对象")
            write_xlsx(args.output, batch_review(args.inputs, mapping))
            return 0
        input_path = Path(args.input)
        args.docx = args.docx or str(input_path.with_name(input_path.stem + "_计算书.docx"))
        args.json = args.json or str(input_path.with_name(input_path.stem + "_结果.json"))
        if args.command == "review":
            args.differences = args.differences or str(
                input_path.with_name(input_path.stem + "_差异.csv")
            )
        _validate_output_paths(args)
        digest = hashlib.sha256(Path(args.input).read_bytes()).hexdigest()
        data = read_workbook(args.input)
        result = calculate(data)
        differences = None
        if args.command == "review":
            from .review.compare import review, write_csv

            mapping = (
                json.loads(Path(args.mapping).read_text(encoding="utf-8")) if args.mapping else None
            )
            if mapping is not None and not isinstance(mapping, dict):
                raise ValueError("评分映射必须是 JSON 对象")
            differences = review(data, result, mapping)
            write_csv(args.differences, differences)
        Path(args.json).write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        make_report(args.docx, data, result, differences, input_sha256=digest)
        return 0
    except (ValueError, TypeError, OSError, KeyError, OverflowError, BadZipFile) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
