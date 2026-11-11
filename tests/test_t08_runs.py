# SPDX-License-Identifier: Apache-2.0
"""运行快照、篡改检测和备份恢复。"""

import json
from pathlib import Path
from zipfile import ZipFile

from openpt.cli import main
from openpt.demo import _a1
from openpt.runs import reproduce, verify_directory


def test_run_pack_restore_and_tamper(tmp_path: Path) -> None:
    """备份解压后只读重现，篡改输入和配置均被清单定位。"""
    source = tmp_path / "input.xlsx"
    _a1(source)
    runs = tmp_path / "runs"
    before = source.read_bytes()
    sample_record = tmp_path / "sample.json"
    sample_record.write_text('{"seed":123}', encoding="utf-8")
    assert (
        main(["run", str(source), "--runs-dir", str(runs), "--sample-record", str(sample_record)])
        == 0
    )
    run = next(runs.iterdir())
    assert source.read_bytes() == before
    assert (run / "input" / "source.xlsx").read_bytes() == before
    assert (run / "input" / "sample.json").read_bytes() == sample_record.read_bytes()
    assert verify_directory(run) == []
    assert reproduce(run)[0] == []
    archive = tmp_path / "package.zip"
    assert main(["pack", str(run), "-o", str(archive)]) == 0
    assert main(["verify", str(archive)]) == 0
    restored = tmp_path / "restored"
    restored.mkdir()
    with ZipFile(archive) as package:
        for name in package.namelist():
            path = restored.joinpath(*name.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(package.read(name))
    assert main(["reproduce", str(restored)]) == 0
    config = restored / "config.json"
    data = json.loads(config.read_text(encoding="utf-8"))
    data["original_config"]["alpha"] = 0.5
    config.write_text(json.dumps(data), encoding="utf-8")
    assert main(["reproduce", str(restored)]) == 1
    assert any("config.json" in item for item in reproduce(restored)[0])
    copied_input = run / "input" / "source.xlsx"
    copied_input.chmod(0o644)
    copied_input.write_bytes(b"altered")
    assert any("source.xlsx" in item for item in reproduce(run)[0])
