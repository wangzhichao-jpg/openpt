# SPDX-License-Identifier: Apache-2.0
"""更新公开示例的中文标签及提示；历史快照需单独重新生成。"""

from pathlib import Path

from openpyxl import load_workbook

from openpt.io.workbook_hints import apply_workbook_hints

ROOT = Path(__file__).resolve().parents[1]


def update(path: Path) -> None:
    """不改数值与原有输入，覆盖公开示例。"""
    book = load_workbook(path)
    apply_workbook_hints(book, example=True)
    book.properties.creator = None
    book.properties.lastModifiedBy = None
    temporary = path.with_name(path.stem + ".openpt-tmp.xlsx")
    book.save(temporary)
    book.close()
    temporary.replace(path)


def main() -> None:
    paths = [*ROOT.joinpath("windows/examples").glob("*.xlsx"), ROOT / "windows/甲醛示例.xlsx"]
    paths.extend(ROOT.joinpath("examples").glob("*.xlsx"))
    paths.extend(ROOT.joinpath("examples/core").glob("*.xlsx"))
    paths.extend(ROOT.joinpath("examples/synthetic").glob("*.xlsx"))
    for path in sorted(paths):
        update(path)
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
