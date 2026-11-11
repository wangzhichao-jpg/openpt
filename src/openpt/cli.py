# SPDX-License-Identifier: Apache-2.0
"""命令行入口。"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .core.homogeneity import analyze as homogeneity
from .core.robust import algorithm_a
from .core.stability import analyze as stability
from .core.zscore import zscore
from .io.excel import read_workbook, template
from .report.docx import make_report


def calculate(data: dict[str, Any]) -> dict[str, Any]:
    """根据输入选择 GL003 与 GL002 计算方法。"""
    cfg = data["config"]
    alpha = float(cfg.get("alpha") or 0.05)
    raw = cfg.get("sigma")
    sigma = float(raw) if raw not in (None, "") else None
    if cfg.get("gbt28043_extension"):
        raise ValueError("GB/T 28043 扩展配置尚未实现")
    result = {}
    if data["homogeneity"]:
        strict = cfg.get("strict_homogeneity", False)
        if not isinstance(strict, bool):
            raise ValueError("strict_homogeneity 必须是布尔值")
        result["均匀性"] = homogeneity(data["homogeneity"], sigma, alpha, strict)
    groups = data["stability"]
    method = cfg.get("stability_method") or "two_sample"
    if groups:
        if "稳定期" not in groups or (method == "two_sample" and "基线" not in groups):
            raise ValueError("稳定性须指定基线及稳定期组")
        raw = cfg.get("reference")
        reference = float(raw) if raw not in (None, "") else None
        result["稳定性"] = stability(
            groups.get("基线"), groups["稳定期"], sigma, alpha, method, reference
        )
        extra = {}
        for name, observations in groups.items():
            if name not in ("基线", "稳定期"):
                extra[name] = stability(
                    groups.get("基线"), observations, sigma, alpha, method, reference
                )
        if extra:
            result["其他稳定性"] = extra
    if data["participants"]:
        result["算法A"] = algorithm_a(
            [p["value"] for p in data["participants"]],
            tolerance=float(cfg.get("algorithm_a_tolerance") or 1e-10),
            max_iterations=int(cfg.get("algorithm_a_max_iterations") or 1000),
            simplified=bool(cfg.get("algorithm_a_simplified", False)),
        )
        sigma_pt = float(cfg["sigma_pt"]) if cfg.get("sigma_pt") not in (None, "") else sigma
        if cfg.get("assigned") not in (None, "") and sigma_pt is not None:
            result["参加者z"] = {
                p["id"]: zscore(
                    p["value"],
                    float(cfg["assigned"]),
                    sigma_pt,
                    float(cfg.get("z_satisfactory") or 2),
                    float(cfg.get("z_unsatisfactory") or 3),
                )
                for p in data["participants"]
            }
    if not result:
        raise ValueError("没有可计算的数据")
    return result


def main(argv: list[str] | None = None) -> int:
    """执行模板、计算或复核命令，返回进程退出码。"""
    parser = argparse.ArgumentParser(prog="openpt")
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("template")
    t.add_argument("output")
    for name in ("run", "review"):
        p = sub.add_parser(name)
        p.add_argument("input")
        p.add_argument("--docx", required=True)
        p.add_argument("--json", required=True)
        if name == "review":
            p.add_argument("--differences", required=True)
            p.add_argument("--mapping", help="可选 JSON 评分映射")
    args = parser.parse_args(argv)
    try:
        if args.command == "template":
            template(args.output)
            return 0
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
        digest = hashlib.sha256(Path(args.input).read_bytes()).hexdigest()
        make_report(args.docx, data, result, differences, input_sha256=digest)
        return 0
    except (ValueError, TypeError, OSError, KeyError, OverflowError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
