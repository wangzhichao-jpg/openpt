# SPDX-License-Identifier: Apache-2.0
"""运行快照与只读重现；绝不执行快照内代码。"""

import hashlib
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from importlib.resources import files
from pathlib import Path
from typing import Any

from . import __version__
from .audit import MANIFEST, _digest, _manifest
from .errors import InputError
from .io.excel import read_workbook
from .reproduce import compare_results


def _json(path: Path, value: Any) -> None:
    """以 UTF-8 写入新建 JSON 文件。"""
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def environment() -> dict[str, Any]:
    """登记软件与依赖版本，不记录本机目录。"""
    versions: dict[str, str | None] = {}
    for name in ("numpy", "scipy", "openpyxl", "python-docx"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    commit: str | None
    try:
        if getattr(sys, "frozen", False):
            raise OSError("打包运行时不查询 Git")
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=5,
        )
        commit = proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    return {
        "openpt": __version__,
        "python": platform.python_version(),
        "dependencies": versions,
        "platform": platform.platform(),
        "git_commit": commit,
    }


def _mapping(path: Path | None) -> dict[str, Any]:
    """读取映射对象。"""
    value = json.loads(path.read_text(encoding="utf-8")) if path else {}
    if not isinstance(value, dict):
        raise InputError("映射必须为 JSON 对象")
    return value


def _snapshot(source: Path, target: Path) -> None:
    """复制原始字节至新文件并设置只读。"""
    with target.open("xb") as stream:
        stream.write(source.read_bytes())
    target.chmod(0o444)


def verify_directory(root: Path) -> list[str]:
    """比较目录实际文件与清单，不运行任何内容。"""
    if root.is_symlink() or (root / MANIFEST).is_symlink():
        raise InputError("运行目录及清单不得是符号链接")
    expected = _manifest((root / MANIFEST).read_bytes())
    actual: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise InputError("运行目录不得包含符号链接")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    wanted = set(expected) | {MANIFEST}
    differences = [f"缺少文件：{p}" for p in sorted(wanted - actual)]
    differences.extend(f"未列入清单：{p}" for p in sorted(actual - wanted))
    for name in sorted(set(expected) & actual):
        with (root / name).open("rb") as stream:
            if _digest(stream) != expected[name]:
                differences.append(f"哈希不一致：{name}")
    return differences


def _calculate_snapshot(root: Path, config: dict[str, Any]) -> tuple[Any, Any, Any]:
    """仅从已保存数据和配置计算。"""
    from .cli import calculate
    from .review.compare import review

    if config.get("input_file") not in ("source.xlsx", "source.csv"):
        raise InputError("运行配置中的输入文件名无效")
    if config.get("command") not in ("run", "review"):
        raise InputError("运行配置中的命令无效")
    source = root / "input" / config["input_file"]
    columns_path = root / "input" / "columns.json"
    columns = _mapping(columns_path if columns_path.exists() else None)
    data = read_workbook(
        source,
        columns,
        encoding=config["encoding"],
        csv_sheet=config["csv_sheet"],
        unit=config["unit"],
        project=config["project"],
    )
    data["config"] = config["expanded_config"]
    if "expanded_assigned_config" in config:
        data["assigned_config"] = config["expanded_assigned_config"]
    for part in data.get("measurands", {}).values():
        part["config"] = {**config["expanded_config"], **part["measurand_overrides"]}
        if "expanded_assigned_config" in config:
            part["assigned_config"] = config["expanded_assigned_config"]
    result = calculate(data, review_mode=config["command"] == "review")
    mapping_path = root / "input" / "mapping.json"
    mapping = _mapping(mapping_path) if mapping_path.exists() else None
    differences = review(data, result, mapping) if config["command"] == "review" else None
    return data, result, differences


def create_run(args: Any, root: Path) -> tuple[Path, Any, Any, Any, str]:
    """创建唯一运行目录，保存输入、配置、环境、结果、计算书及清单。"""
    from .report.docx import make_report
    from .report.multi import export_reports
    from .review.compare import write_csv

    source = Path(args.input)
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + digest[:8]
    directory = root / name
    directory.mkdir(exist_ok=False)
    try:
        input_dir = directory / "input"
        input_dir.mkdir()
        filename = "source" + source.suffix.lower()
        target = input_dir / filename
        with target.open("xb") as stream:
            stream.write(raw)
        target.chmod(0o444)
        for attr, filename_optional in (
            ("columns", "columns.json"),
            ("mapping", "mapping.json"),
            ("sample_record", "sample.json"),
        ):
            value = getattr(args, attr, None)
            if value:
                _snapshot(Path(value), input_dir / filename_optional)
        columns = _mapping(input_dir / "columns.json" if args.columns else None)
        from .io.validation import inspect_input

        issues = inspect_input(target, columns, encoding=args.encoding, csv_sheet=args.csv_sheet)
        if issues:
            raise InputError(
                "输入校验问题："
                + json.dumps([issue.to_dict() for issue in issues], ensure_ascii=False, default=str)
            )
        data = read_workbook(
            target,
            columns,
            encoding=args.encoding,
            csv_sheet=args.csv_sheet,
            unit=args.unit,
            project=args.project,
        )
        defaults = json.loads(
            files("openpt.config").joinpath("default.json").read_text(encoding="utf-8")
        )
        expanded = {
            **defaults,
            "sigma_source": None,
            "sigma_stage": None,
            "observation_level": "unit_means",
            "stability_design": "independent",
            "reference_uncertainty_negligible": True,
            "reference_source": None,
            "score_type": "z",
            "en_limit": 1,
            "algorithm_s_max_iterations": 1000,
            "algorithm_s_stop_rule": "gl002",
            "algorithm_s_tolerance": 1e-12,
            "display_sig_digits": 4,
            "display_mean_decimals": None,
            "display_ss_decimals": 3,
            "display_z_decimals": 2,
            "assigned": None,
            "sigma_pt": None,
            "mean1": None,
            "mean2": None,
            "s1": None,
            "s2": None,
            "n1": None,
            "n2": None,
            "sigma_composite": None,
            "sigma_ss": None,
            "sigma_composite_digits": 1,
            "reported_stability_sigma": None,
            **{k: v for k, v in data["config"].items() if v not in (None, "")},
        }
        assigned_defaults = {
            "method": None,
            "value": None,
            "uncertainty": None,
            "source": "",
            "uncertainty_source": "",
            "consensus_method": "robust_mean",
            "sigma_temporary": None,
            "sigma_final": None,
            "sigma_procedure": "",
            "u_hom": 0.0,
            "u_stab": 0.0,
            "hom_mapping": "none",
            "stab_mapping": "none",
            "hom_in_base": False,
            "stab_in_base": False,
            "known_components": None,
            "expert_values": None,
            "U_assigned": None,
            "k_assigned": None,
            "independent": None,
        }
        config = {
            "command": args.command,
            "input_file": filename,
            "encoding": args.encoding,
            "csv_sheet": args.csv_sheet,
            "unit": args.unit,
            "project": args.project,
            "original_config": data["config"],
            "expanded_config": expanded,
            "column_mapping": columns,
            "assigned_config": data.get("assigned_config", {}),
            "assigned_defaults": assigned_defaults,
            "expanded_assigned_config": {**assigned_defaults, **data.get("assigned_config", {})},
        }
        _json(directory / "config.json", config)
        _json(directory / "environment.json", environment())
        data, result, differences = _calculate_snapshot(directory, config)
        _json(directory / "result.json", result)
        if differences is not None:
            write_csv(directory / "differences.csv", differences)
        make_report(directory / "report.docx", data, result, differences, input_sha256=digest)
        export_reports(
            directory / "report.docx", directory / "report.xlsx", directory / "report.html", result
        )
        (directory / "log.txt").write_text("完成；软件不自动放行。\n", encoding="utf-8")
        hashes = {}
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                with path.open("rb") as stream:
                    hashes[path.relative_to(directory).as_posix()] = _digest(stream)
        _json(directory / MANIFEST, {"files": hashes})
        return directory, data, result, differences, digest
    except BaseException:
        # 只删除本次成功新建的目录，不触碰既有运行目录。
        for path in directory.rglob("*"):
            if path.is_file():
                path.chmod(0o644)
        shutil.rmtree(directory)
        raise


def reproduce(root: Path) -> tuple[list[str], list[str]]:
    """先核对清单，再基于快照重算并比较结果；不写入运行目录。"""
    differences = verify_directory(root)
    if differences:
        return differences, []
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    saved_environment = json.loads((root / "environment.json").read_text(encoding="utf-8"))
    current = environment()
    warnings = [
        key
        for key in ("openpt", "python", "dependencies", "platform", "git_commit")
        if saved_environment.get(key) != current.get(key)
    ]
    _, actual, _ = _calculate_snapshot(root, config)
    expected = json.loads((root / "result.json").read_text(encoding="utf-8"))
    return compare_results(expected, actual), warnings
