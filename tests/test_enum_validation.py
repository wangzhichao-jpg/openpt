# SPDX-License-Identifier: Apache-2.0
"""非法枚举必须在三个入口一致拒绝。"""

from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st
from openpyxl import load_workbook

from openpt.cli import main
from openpt.config.catalog import ENUMS
from openpt.io.excel import template
from openpt.io.validation import inspect_input


@settings(max_examples=25, deadline=None)
@given(
    st.sampled_from(
        [
            k
            for k in ENUMS
            if k
            not in (
                "decision",
                "stability_period_options.kind",
                "候选批次.状态",
                "assigned_method",
                "independent",
                "hom_in_base",
                "stab_in_base",
                "trans_in_base",
                "trans_in_stab",
                "consensus_method",
                "hom_source",
                "hom_mapping",
                "stab_mapping",
                "trans_mapping",
                "stability_disposition",
            )
        ]
    ),
    st.text(alphabet="xyz789", min_size=1, max_size=8),
)
def test_invalid_enum_is_rejected(field: str, value: str) -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "input.xlsx"
        template(path)
        book = load_workbook(path)
        book["项目信息"]["B2"] = "合成"
        book["项目信息"]["B3"] = "mg"
        for unit in range(2):
            for repeat in range(2):
                book["均匀性"].append([unit + 1, repeat + 1, unit + repeat / 10, "mg"])
        config = book["方法配置"]
        for row in config.iter_rows(min_row=2):
            if str(row[0].value or "").endswith(f"（{field}）"):
                row[1].value = value
                break
        else:
            config.append([field, value])
        book.save(path)
        problems = inspect_input(path)
        assert any(
            issue.category == "INVALID_CONFIG" and issue.sheet == "方法配置" for issue in problems
        )
        assert main(["validate", str(path)]) == 1
        assert main(["run", str(path), "--runs-dir", str(Path(directory) / "run")]) == 2
        assert main(["review", str(path), "--runs-dir", str(Path(directory) / "review")]) == 2
