<!-- 由 tools/sync_readme.py 从 README.en.md 生成，请勿直接修改。 -->
# OpenPT — Proficiency Testing Sample Evaluation and Assigned Value Tool

[简体中文](../README.md) | English

OpenPT (能力验证样品评价与定值工具) is a free, open-source tool for proficiency testing (PT) providers. It evaluates sample homogeneity and stability, determines assigned values, and calculates performance statistics, then generates a result summary and a Word calculation report. Methods follow CNAS-GL002 / GL003 and GB/T 28043-2019 (ISO 13528). The application interface, templates and reports are in Simplified Chinese.

## Download the Windows portable version

- **GitHub:** [Download Windows portable 0.2.5](https://github.com/wangzhichao-jpg/openpt/releases/tag/v0.2.5)
- **Gitee (mirror in mainland China):** [Download Windows portable 0.2.5](https://gitee.com/bigtaurus/openpt/releases/tag/v0.2.5)

Version 0.2.5 includes five examples: formaldehyde, tensile strength of materials, tapped density of granules, digital multimeter, and a GB/T 28043 synthetic testing example. The window lists σ_pt and every participant's score with its evaluation, display decimals are configurable, and stability criteria can be chosen per time group (e.g. storage vs. transport). When a workbook is misconfigured or a result cannot be evaluated, the program lists every problem with its worksheet, row and current value, and explains why, with a suggested fix.

Unzip the whole Windows ZIP and double-click the program. No Python, other runtime or administrator rights are needed. Licensed under Apache-2.0.

Windows 11 Smart App Control may block unsigned applications. This program is not currently code-signed: the project has selected SignPath Foundation's free code signing for open-source projects as the future option, but the application has not been submitted yet. See the [user guide (Chinese)](../docs/使用手册.md#smart-app-control) for options.

## Windows quick start

1. Unzip `能力验证样品评价与定值工具_Windows.zip` and double-click `能力验证样品评价与定值工具.exe` in the extracted folder.
2. Click “载入甲醛示例” (load the formaldehyde example), or click “选择数据文件” (select data file) and choose a workbook from the “示例案例” (examples) folder next to the program. You can also click “新建数据模板” (new data template), fill it in and save it.
3. Click “开始计算” (start calculation) to see homogeneity, each stability time group and the assigned value in the window.
4. Click “打开计算书” (open report) or “打开结果目录” (open result folder). Results are saved in the `OpenPT结果` folder under your Documents.

Calculation methods are set in the workbook; the program never modifies the input file. See the [user guide (Chinese)](../docs/使用手册.md) for how to fill in the workbook.

## Development and validation

The source code and the internal calculation pipeline are kept in this repository. Engineering tests cover Windows, Linux and independent cross-checks in R. See the [command-line and engineering reference (Chinese)](../docs/开发者命令行参考.md) for developers and [THIRD_PARTY_LICENSES.md](../THIRD_PARTY_LICENSES.md) for third-party licenses. The Windows portable bundle is built and smoke-tested on native Windows by `.github/workflows/windows-build.yml`.
