# SPDX-License-Identifier: Apache-2.0
"""命令行入口。"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from .core.homogeneity import analyze as homogeneity
from .core.robust import algorithm_a
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
    result = {
        "算法A": algorithm_a(
            values,
            tolerance=float(_option(cfg, "algorithm_a_tolerance", 1e-10)),
            max_iterations=int(_option(cfg, "algorithm_a_max_iterations", 1000)),
            simplified=simplified,
            rule=str(_option(cfg, "algorithm_a_rule", "gl002")),
        ).to_dict()
    }
    # 绝对容差对照独立于选定停止规则，供附录和敏感性提示使用。
    result["算法A_收敛对照"] = algorithm_a(
        values, rule="absolute", tolerance=1e-12, max_iterations=10000
    ).to_dict()
    sigma_pt = float(cfg["sigma_pt"]) if cfg.get("sigma_pt") not in (None, "") else sigma
    if cfg.get("assigned") not in (None, "") and sigma_pt is not None:
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
        result["均匀性"] = homogeneity(data["homogeneity"], sigma, alpha, strict).to_dict()
    groups = data["stability"]
    method = cfg.get("stability_method") or "two_sample"
    if groups:
        if "稳定期" not in groups or (method == "two_sample" and "基线" not in groups):
            raise ValueError("稳定性须指定基线及稳定期组")
        raw = cfg.get("reference")
        reference = float(raw) if raw not in (None, "") else None
        result["稳定性"] = stability(
            groups.get("基线"), groups["稳定期"], sigma, alpha, method, reference
        ).to_dict()
        extra = {}
        for name, observations in groups.items():
            if name not in ("基线", "稳定期"):
                extra[name] = stability(
                    groups.get("基线"), observations, sigma, alpha, method, reference
                ).to_dict()
        if extra:
            result["其他稳定性"] = extra
    if data["participants"]:
        result.update(_participant_results(data, sigma))
    if not result:
        raise ValueError("没有可计算的数据")
    return result


def _parser() -> argparse.ArgumentParser:
    """创建带中文说明的命令行参数。"""
    parser = argparse.ArgumentParser(prog="openpt", description="能力验证统计工作台")
    parser.add_argument("--version", action="version", version="openpt 0.0.1", help="显示版本")
    sub = parser.add_subparsers(dest="command", required=True, title="命令")
    t = sub.add_parser("template", help="生成空白 Excel 模板")
    t.add_argument("output", help="模板文件路径")
    demo = sub.add_parser("demo", help="生成公开演示数据及计算结果")
    demo.add_argument("directory", help="示例输出目录")
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
