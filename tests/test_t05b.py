# SPDX-License-Identifier: Apache-2.0
"""用途判据的临时、最终和缺失状态。"""

from openpt.core.homogeneity import analyze


def test_sigma_stages() -> None:
    """GL003 4.2、4.3 的 F 和用途判断保持独立。"""
    values = [[1, 2], [2, 3]]
    missing = analyze(values)
    temporary = analyze(values, 2, sigma_source="经验值", sigma_stage="temporary")
    final = analyze(values, 2, sigma_source="其他", sigma_stage="final")
    assert missing.Ss_status == "NOT_EVALUATED" and missing.Ss_pass is None
    assert temporary.Ss_status == "PROVISIONAL" and temporary.sigma_source == "经验值"
    assert final.Ss_status == "OK" and final.sigma_stage == "final"
    assert missing.F_pass == temporary.F_pass == final.F_pass
