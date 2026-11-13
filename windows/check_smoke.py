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
    assert "直流8V" in summary and "交流2V" in summary
    assert "限值 = 0.0002" in summary and "限值 = 0.0004" in summary
    expected = {"标准器A|直流8V": 0.00017, "标准器A|交流2V": 0.0001}
    assert set(points) == set(expected)
    assert all(math.isclose(points[k]["delta_max"], v, abs_tol=1e-12) for k, v in expected.items())
    assert all(point["conclusion"] is True for point in points.values())
    assert math.isclose(r["指定值与不确定度"]["value"], 8.000025, abs_tol=1e-12)
    assert math.isclose(r["参加者统计量"]["参加者A"]["En"]["value"], 0.1624591083, rel_tol=1e-9)
    print("Transfer GUI smoke checks passed.")
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
