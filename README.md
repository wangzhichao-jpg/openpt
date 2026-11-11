# OpenPT 0.0.1

能力验证统计工作台原型，提供单因子 ANOVA、Ss、稳定性 t 检验、算法 A、中位数与 NIQR、z、Excel 模板、复核差异表与 DOCX。计算结果供具备资质的人员复核使用；方法依据为 CNAS-GL003:2018、CNAS-GL002:2018，用户可配置。**当前尚未通过全部验收，不得用于正式评价或直接发布。**

## 安装

Windows（Python 3.10～3.13）：

```powershell
py -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[test]"
```

若 Python 的 `Scripts` 目录不在 PATH，使用 `py -m openpt demo 演示目录`、
`py -m openpt run input.xlsx` 等命令。可选 Wine 测试及其局限见
[Windows 兼容性测试](docs/Windows兼容性测试.md)。

Linux/macOS：

```sh
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e '.[test]'
```

需要可选库交叉核对时单独安装 `.[crosscheck]`。`requirements.lock` 仅记录开发机 Python 3.12 的一次解析；跨平台使用项目声明的版本范围。实际运行平台和完整许可证必须审查，见 `THIRD_PARTY_LICENSES.md`。

## 快速开始

```text
openpt template input.xlsx
openpt run input.xlsx
openpt review input.xlsx --mapping examples/mapping.json
openpt demo demo-output
openpt --version
python -m pytest -m "not internal"
```

默认结果写在输入文件旁；`--docx`、`--json` 和 `--differences` 可覆盖路径。`demo` 生成公开示例，检测到 LibreOffice 时额外转换 PDF。

![公开示例计算书截图](docs/计算书截图.png)

填入项目名称、统一单位和均匀性表，每个包装单元每次重复一行；支持平衡及不平衡重复，不平衡属于待审核扩展方法。稳定性表的时间组使用 `基线` 和 `稳定期`。参考输入 `examples/GL003_A1.xlsx`。所有输入必须是实际值，不接受公式。复核声称值需填写统计量、数值、显示小数位及来源。报告模型可填 `recommended`、`repeats_pooled`、`repeats_welch`、`displayed_summary`。最后一种还需在配置表输入 `mean1`、`mean2`、`s1`、`s2`、`n1`、`n2`；多时点复核需在声称值表的“时间组”列指定时点。评分映射通过 `--mapping` 加载。差异清单按 `DIFFERENCE`、`NOTE`、`MATCH` 分组排序；报告模型能复现时，推荐模型不同只记为提示，不直接认定报告错误。`REPORT_RULE_UNKNOWN` 表示绝对容差仅作候选，原报告停止规则尚待确认；`STOP_RULE_SENSITIVITY` 表示停止规则影响显示结果。无更具体类别的提示使用 `REVIEW_NOTE`，待核查差异使用 `REVIEW_REQUIRED`。

## 配置与边界

方法配置表 `alpha` 默认 0.05；`sigma` 缺省时相应提示未评价；`strict_homogeneity` 默认 FALSE；`stability_method` 默认 `two_sample`，可设 `one_sample` 并提供 `reference`；`assigned` 和 `sigma_pt` 用于 z；未提供 `sigma_pt` 时回退到 `sigma`。稳定性推荐模型使用包装单元均值。算法 A 的 `algorithm_a_rule` 默认 `gl002`（第三有效位及对应位），可选 `absolute`（使用 `algorithm_a_tolerance`）或 `simplified`；可配置 `algorithm_a_max_iterations`。程序另算绝对容差收敛对照并放入计算书附录，显示位数不同时提示停止规则敏感。DOCX 参加者 z 值默认保留两位小数，配置 `display_z_decimals` 可设 0～12 位；CSV 和 JSON 不按此设置截断。不平衡均匀性方法及分位数定义见 ADR-002。相关和配对稳定性设计必须在模板中显式声明，程序将阻断结论；参考值不确定度不可忽略时亦须显式声明并阻断。程序不能自动判定设计独立性。全部重复值仅用于复核，常规运行不接受。指定值和不确定度模型、更多比分数及扩展配置均尚未实现。

DOCX 指定中文宋体、西文 Times New Roman，不附带字体；若系统缺字，请安装有授权的相应字体或在文档编辑器中选择已安装的中文字体后重新导出。不同平台排版需逐页检查。

公开仓库不包含历史项目数据；内部材料必须保存在仓库外，设置 `OPENPT_INTERNAL_DIR` 后才运行标记为 internal 的测试。仅将已授权的材料存入该目录。

## 引用与许可

引用软件请参见 `CITATION.cff`。项目代码采用 Apache-2.0，详见 `LICENSE` 和 `NOTICE`；第三方许可及原生运行库限制见 `THIRD_PARTY_LICENSES.md`。
