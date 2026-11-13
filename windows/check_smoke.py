# SPDX-License-Identifier: Apache-2.0
"""检查打包 EXE 生成的结果，与合成示例的独立复算值比较。"""

import json
import math
import sys
from pathlib import Path

root = Path(sys.argv[1])
assert (root / "gui-smoke.txt").is_file(), "GUI 未完成启动及计算"
runs = [p for p in root.iterdir() if p.is_dir()]
assert len(runs) == 1
run = runs[0]
assert (run / "report.docx").is_file()
r = json.loads((run / "result.json").read_text(encoding="utf-8"))
if len(sys.argv) > 2 and sys.argv[2] == "传递":
    summary = (root / "gui-smoke.txt").read_text(encoding="utf-8")
    points = r["传递标准稳定性"]
    assert "不适用样品间均匀性检验" in summary
    assert "35%RH" in summary and "55%RH" in summary and "限值 = 0.8" in summary
    assert all(math.isclose(point["delta_max"], 0.16, abs_tol=1e-12) for point in points.values())
    assert all(point["conclusion"] is True for point in points.values())
    assert math.isclose(r["指定值与不确定度"]["value"], 0.1, abs_tol=1e-12)
    print("传递样 GUI smoke checks passed.")
    raise SystemExit(0)

for actual, expected in [
    (r["均匀性"]["Ss"], 0.0642585921622),
    (r["均匀性"]["threshold"], 0.3),
    (r["稳定性"]["difference"], 0.12),
    (r["其他稳定性"]["运输期"]["difference"], 0.06),
    (r["指定值与不确定度"]["value"], 100.0405652277587),
    (r["指定值与不确定度"]["u"], 0.22326622377769484),
]:
    assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-10), (actual, expected)
assert r["均匀性"]["conclusion"] is True
assert r["稳定性"]["mean_difference_pass"] is True
assert r["其他稳定性"]["运输期"]["mean_difference_pass"] is True
print("GUI smoke checks passed.")
