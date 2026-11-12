# SPDX-License-Identifier: Apache-2.0
"""命令行入口。"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from . import __version__
from .core.assigned import assign_value
from .core.gbt28043 import homogeneity as gbt_homogeneity
from .core.gbt28043 import stability as gbt_stability
from .core.homogeneity import analyze as homogeneity
from .core.robust import algorithm_a, algorithm_s, median_niqr
from .core.scores import performance_score
from .core.stability import analyze as stability
from .core.zscore import zscore
from .errors import InputError
from .io.excel import template
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
    for key in ("known_components", "expert_values"):
        if a.get(key) not in (None, ""):
            if not isinstance(a[key], str):
                raise InputError(f"{key} 须为逗号分隔的数值列表")
            try:
                options[key] = [float(item.strip()) for item in a[key].split(",")]
            except ValueError:
                raise InputError(f"{key} 须为逗号分隔的数值列表") from None
    assigned = assign_value(
        a["method"], participants=[p["value"] for p in data["participants"]], **options
    )
    assigned_details = assigned.to_dict()
    assigned_details.update(
        {key: a.get(key) for key in ("U_assigned", "k_assigned", "independent")}
    )
    result: dict[str, Any] = {"指定值与不确定度": assigned_details}
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


def calculate(data: dict[str, Any], review_mode: bool = False) -> dict[str, Any]:
    """根据输入选择 GL003 与 GL002 计算方法。"""
    cfg = data["config"]
    alpha = float(_option(cfg, "alpha", 0.05))
    raw = cfg.get("sigma")
    sigma = float(raw) if raw not in (None, "") else None
    if cfg.get("gbt28043_extension"):
        raise ValueError("旧配置 gbt28043_extension 不支持；请使用 criterion_standard")
    standard = _option(cfg, "criterion_standard", "gl003")
    if standard not in ("gl003", "gbt28043"):
        raise InputError("criterion_standard 应为 gl003 或 gbt28043")
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
        if standard == "gbt28043":
            result["GB/T均匀性"] = gbt_homogeneity(data["homogeneity"], sigma)
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
        if level == "all_repeats" and not review_mode:
            raise InputError("全部重复值仅供复核模型使用，不可用于常规结论")
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
        if level == "all_repeats":
            result["报告层级稳定性"] = stability(
                groups.get("基线"),
                groups["稳定期"],
                sigma,
                alpha,
                method,
                reference,
                model="repeats_pooled",
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
        if standard == "gbt28043":
            if method != "two_sample":
                raise InputError("GB/T 28043 稳定性模式需要两组样品")
            u1_raw, u2_raw = cfg.get("stability_u1"), cfg.get("stability_u2")
            u1 = float(u1_raw) if u1_raw not in (None, "") else None
            u2 = float(u2_raw) if u2_raw not in (None, "") else None
            independent = design_options["design"] == "independent"
            result["GB/T稳定性"] = {
                name: gbt_stability(
                    groups["基线"], observations, sigma, u1=u1, u2=u2, independent=independent
                )
                for name, observations in groups.items()
                if name != "基线"
            }
    if data["participants"]:
        result.update(_participant_results(data, sigma))
    if data.get("assigned_config", {}).get("method"):
        result.update(_assigned_results(data))
    if data.get("algorithm_s_values"):
        result["算法S"] = algorithm_s(
            data["algorithm_s_values"],
            data["algorithm_s_df"],
            max_iterations=int(_option(cfg, "algorithm_s_max_iterations", 1000)),
            stop_rule=str(_option(cfg, "algorithm_s_stop_rule", "gl002")),
            tolerance=float(_option(cfg, "algorithm_s_tolerance", 1e-12)),
        ).to_dict()
    if not result:
        raise ValueError("没有可计算的数据")
    if standard == "gbt28043":
        result["标准模式"] = standard
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
    sampling = sub.add_parser("sample", help="随机抽样及生成重复检测顺序")
    sampling.add_argument("--units", type=int, required=True, help="总体单元数")
    sampling.add_argument("--pick", type=int, required=True, help="抽样数")
    sampling.add_argument("--seed", type=int, required=True, help="非负随机种子")
    sampling.add_argument("--strata", help="分层 JSON 文件")
    sampling.add_argument("--output", default="sample-output", help="新的输出目录")
    decision = sub.add_parser("decide", help="追加人工决定并生成新版本计算书")
    decision.add_argument("directory", help="已有运行目录")
    decision.add_argument("--item", required=True, help="复核条目")
    decision.add_argument("--allow-new-item", action="store_true", help="允许登记结果之外的条目")
    decision.add_argument("--decision", required=True, choices=("接受", "退回", "需补充"))
    decision.add_argument("--by", required=True, dest="person", help="决定人员")
    decision.add_argument("--note", default="", help="决定备注")
    reproduction = sub.add_parser("reproduce", help="校验快照并重新计算")
    reproduction.add_argument("directory", help="已有运行目录")
    pack = sub.add_parser("pack", help="按 manifest.json 打包已有运行目录")
    pack.add_argument("directory", help="运行目录")
    pack.add_argument("-o", "--output", required=True, help="新的 ZIP 文件")
    verify = sub.add_parser("verify", help="检查 ZIP 中的清单和文件哈希")
    verify.add_argument("archive", help="审计包 ZIP")
    validate = sub.add_parser("validate", help="只读检查测量表并输出 JSON 问题清单")
    validate.add_argument("input", help="XLSX 或 CSV 文件")
    validate.add_argument("--columns", help="标准字段到原始列名的 JSON 映射")
    validate.add_argument(
        "--encoding", default="utf-8-sig", help="CSV 编码，默认 UTF-8（兼容 BOM）"
    )
    validate.add_argument("--sheet", default="均匀性", help="CSV 测量表类型")
    demo = sub.add_parser("demo", help="生成公开演示数据及计算结果")
    demo.add_argument("directory", help="示例输出目录")
    batch = sub.add_parser("review-batch", help="批量复核并输出 XLSX 差异总表")
    batch.add_argument("inputs", nargs="+", help="输入 Excel 文件")
    batch.add_argument("--output", required=True, help="差异总表 XLSX 路径")
    batch.add_argument("--mapping", help="可选 JSON 评分映射")
    for name in ("run", "review"):
        p = sub.add_parser(name, help="运行计算" if name == "run" else "复核报告")
        p.add_argument("input", help="输入 Excel 或 CSV 文件")
        p.add_argument("--columns", help="JSON 列映射文件")
        p.add_argument("--encoding", default="utf-8-sig", help="CSV 编码")
        p.add_argument("--csv-sheet", default="均匀性", help="CSV 对应的测量表")
        p.add_argument("--unit", help="CSV 测量单位，须明确提供")
        p.add_argument("--project", default="CSV 输入", help="CSV 项目名称")
        p.add_argument(
            "--runs-dir", default=os.environ.get("OPENPT_RUNS_DIR", "runs"), help="运行记录根目录"
        )
        p.add_argument("--sample-record", help="可选抽样记录文件，原样保存")
        p.add_argument("--docx", help="计算书路径；默认写入输入文件旁")
        p.add_argument("--json", help="结果 JSON 路径；默认写入输入文件旁")
        if name == "review":
            p.add_argument("--differences", help="差异 CSV 路径；默认写入输入文件旁")
            p.add_argument("--mapping", help="可选 JSON 评分映射")
    return parser


def _deny_run_write(path: str | Path) -> None:
    """拒绝将普通输出写入任何已有运行目录。"""
    target = Path(path).resolve()
    if any((parent / "manifest.json").is_file() for parent in (target, *target.parents)):
        raise ValueError("不得修改已有运行目录")


def _validate_output_paths(args: argparse.Namespace) -> None:
    """防止输出文件覆盖输入、映射文件或彼此覆盖。"""
    outputs = [Path(args.docx).resolve(), Path(args.json).resolve()]
    protected = {Path(args.input).resolve()}
    if args.columns:
        protected.add(Path(args.columns).resolve())
    if args.sample_record:
        protected.add(Path(args.sample_record).resolve())
    if args.command == "review":
        outputs.append(Path(args.differences).resolve())
        if args.mapping:
            protected.add(Path(args.mapping).resolve())
    if len(set(outputs)) != len(outputs) or protected.intersection(outputs):
        raise ValueError("输出路径不得覆盖输入文件、映射文件或其他输出文件")
    if any(path.is_relative_to(Path(args.runs_dir).resolve()) for path in outputs):
        raise ValueError("常规输出不得写入运行记录根目录")
    for path in outputs:
        _deny_run_write(path)


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
            _deny_run_write(args.output)
            template(args.output)
            return 0
        if args.command == "sample":
            from .sampling import sample, write_sample

            strata = (
                json.loads(Path(args.strata).read_text(encoding="utf-8")) if args.strata else None
            )
            if strata is not None and not isinstance(strata, dict):
                raise ValueError("分层必须是 JSON 对象")
            record = sample(args.units, args.pick, args.seed, strata)
            _deny_run_write(args.output)
            write_sample(args.output, record)
            for warning in record["warnings"]:
                print(warning)
            return 0
        if args.command == "decide":
            from .decisions import decide

            decide(
                Path(args.directory),
                args.item,
                args.decision,
                args.person,
                args.note,
                allow_new_item=args.allow_new_item,
            )
            print("已记录人工决定；软件不自动放行。")
            return 0
        if args.command == "reproduce":
            from .runs import reproduce

            try:
                audit_differences, warnings = reproduce(Path(args.directory))
            except (ValueError, TypeError, OSError, KeyError, OverflowError, BadZipFile):
                print("不可重现：清单、配置或输入无法读取或无效")
                return 1
            for item in warnings:
                print(f"环境版本不同：{item}")
            print("不可重现" if audit_differences else "可重现")
            for difference in audit_differences:
                print(difference)
            return 1 if audit_differences else 0
        if args.command == "pack":
            from .audit import pack_directory

            _deny_run_write(args.output)
            pack_directory(args.directory, args.output)
            return 0
        if args.command == "verify":
            from .audit import verify_zip

            audit_differences = verify_zip(args.archive)
            print(
                "\n".join(audit_differences)
                if audit_differences
                else "清单哈希一致（未验证清单真实性）"
            )
            return 1 if audit_differences else 0
        if args.command == "validate":
            from .io.validation import inspect_input

            columns = (
                json.loads(Path(args.columns).read_text(encoding="utf-8")) if args.columns else {}
            )
            if not isinstance(columns, dict):
                raise ValueError("列映射必须为 JSON 对象")
            issues = inspect_input(
                args.input, columns, encoding=args.encoding, csv_sheet=args.sheet
            )
            print(
                json.dumps([issue.to_dict() for issue in issues], ensure_ascii=False, default=str)
            )
            return 1 if issues else 0
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
            _deny_run_write(args.output)
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
        from .runs import create_run

        _deny_run_write(args.runs_dir)
        directory, data, result, differences, digest = create_run(args, Path(args.runs_dir))
        if differences is not None:
            from .review.compare import write_csv

            write_csv(args.differences, differences)
        print(f"运行记录：{directory.name}")
        Path(args.json).write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        make_report(args.docx, data, result, differences, input_sha256=digest)
        return 0
    except OSError as exc:
        print(f"错误：文件操作失败（{exc.strerror or '系统错误'}）", file=sys.stderr)
        return 2
    except (ValueError, TypeError, KeyError, OverflowError, BadZipFile) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
