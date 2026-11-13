# OpenPT 0.2.1（本地源码修订，未公开发布）

能力验证统计工作台原型，帮助机构对自己的样品开展**均匀性检验、稳定性检验和定值**：通过 Excel 输入数据与方法，运行命令，查看含三个核心结果的计算书。也提供已有报告的复核和归档功能，但不需要先有报告。计算和扩展方法须由具备专业能力的人员结合实验设计核查；软件不自动放行样品。当前尚未公开发布，不得将原型直接用于正式评价。

## 安装

Windows（Python 3.10～3.13）：

```powershell
py -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple .
```

若 Python 的 `Scripts` 目录不在 PATH，使用 `py -m openpt demo 演示目录`、
`py -m openpt run input.xlsx` 等命令。可选 Wine 测试及其局限见
[Windows 兼容性测试](docs/Windows兼容性测试.md)。

Linux（用于开发和持续集成）：

```sh
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e '.[test]'
```

需要可选库交叉核对时单独安装 `.[crosscheck]`。`requirements.lock` 仅记录开发机 Python 3.12 的一次解析；跨平台使用项目声明的版本范围。实际运行平台和完整许可证必须审查，见 `THIRD_PARTY_LICENSES.md`。

## 核心流程：均匀性 → 稳定性 → 定值

在已准备好的 Windows 环境中，从源码根目录执行：

```powershell
py -m openpt --version
py -m openpt template input.xlsx
# 用 Excel 填写 input.xlsx 并保存，再执行：
py -m openpt validate input.xlsx
py -m openpt run input.xlsx --runs-dir runs
```

在“项目信息”填项目名和单位；“均匀性”填包装单元、重复编号及测量值；“稳定性”填时间组、单元及重复值。“方法配置”按实际设计选择均匀性与稳定性方法、判据标准差 `sigma` 及其来源；“指定值与不确定度”填写选定方法、来源、数值及不确定度，或录入参加者结果以计算公议值。报告声称值可以留空；只需单项计算时也允许不填其他表。模板不接受公式。完整字段及独立性要求见[使用手册](docs/使用手册.md)。

检查通过只代表所覆盖的输入检查未发现问题。`run` 默认只在新的 `runs/<运行编号>/` 输出 `report.docx`、`result.json` 等；路径以屏幕显示为准。打开计算书，依次核对均匀性、稳定性、指定值及标准不确定度。若需副本，可显式指定 `--docx` 或 `--json`；`review`、差异对照和打包是可选支线。

两个完全虚构的贯穿示例可直接验证，无需填报告声称值：

```powershell
py -m openpt validate examples/core/core_known.xlsx
py -m openpt run examples/core/core_known.xlsx --runs-dir runs-known
py -m openpt validate examples/core/core_consensus.xlsx
py -m openpt run examples/core/core_consensus.xlsx --runs-dir runs-consensus
```

A 为外部已评定已知值及其标准不确定度；B 复用 A 的虚构均稳数据，另用虚构参加者结果按算法 A 算公议值。示例分量和来源仅为演示，不是对真实项目的评定。

### 选择并登记定值方式

| 方法 | 软件实际处理 |
|---|---|
| `known` 已知值 | 登记外部已评定的值与标准不确定度；也可合成独立的制备不确定度分量，但不从配料量计算值 |
| `certified` 有证参考值 | 登记证书或外部已评定的值及标准不确定度，不自动识别证书 |
| `reference` 参考测量 | 登记外部参考测量已评定的值及标准不确定度 |
| `expert_consensus` 专家公议 | 登记外部公议值及标准不确定度；或对独立同精度专家值计算平均值和标准误，适用性须核查 |
| `participant_consensus` 参加者公议 | 从参加者数据计算算法 A 稳健均值或中位数及程序支持的标准不确定度公式 |

在“指定值与不确定度”填写外部评定的 `u_hom`、`u_stab`，用 `hom_mapping`、`stab_mapping` 选择 `assigned` 计入指定值标准不确定度，或 `sigma_prime` 计入后续评价标准差；无需计入时选 `none`。基础不确定度已含某分量时如实设置 `hom_in_base`、`stab_in_base`，不要重复映射。分量须由人员依据适当方法评定，不能从均稳检通过自动推算；程序不能发现未声明的相关性或重复计入。

均匀性与稳定性可使用长表或宽表；常规技术重复默认每单元至少两次。破坏性单测应显式选择 `replicate_type=single`，均匀性使用 GB/T 28043-2019 B.1.2 单测标准差法；不要同时显式选择 GL003 4.2/4.3 主判据或严格配置。不平衡设计及扩展方法须核查适用性。多个被测量按量隔离，见 ADR-006。

### 可选：报告复核

`openpt review input.xlsx --mapping examples/mapping.json` 可复核已有报告；`openpt review-batch input1.xlsx input2.xlsx --output differences.xlsx` 可批量复核。`openpt demo demo-output` 生成合成演示。复核声称值需填写统计量、数值、显示小数位及来源。报告模型可填 `recommended`、`repeats_pooled`、`repeats_welch`、`displayed_summary`。最后一种还需在配置表输入 `mean1`、`mean2`、`s1`、`s2`、`n1`、`n2`；多时点复核需在声称值表的“时间组”列指定时点。评分映射通过 `--mapping` 加载。差异清单按 `DIFFERENCE`、`NOTE`、`MATCH` 分组排序；报告模型能复现时，推荐模型不同只记为提示，不直接认定报告错误。`REPORT_RULE_UNKNOWN` 表示绝对容差仅作候选，原报告停止规则尚待确认；`STOP_RULE_SENSITIVITY` 表示停止规则影响显示结果。无更具体类别的提示使用 `REVIEW_NOTE`，待核查差异使用 `REVIEW_REQUIRED`。

## 候选批次

新模板的“候选批次”表可登记候选、失败、选用和弃用状态；失败或弃用须填理由，关联批次必须存在。预实验结果可填写英文逗号分隔的有限数，计算书列出均值与样本标准差（单个结果无法计算标准差）。选择由人员登记，软件不自动选择或放行。旧模板可以继续使用。

## 实验性只读导入检查

`openpt validate input.xlsx [--columns columns.json]` 只读检查已有的均匀性、稳定性和参加者测量表，输出 JSON 问题列表。列映射 JSON 格式示例：`{"均匀性": {"单元编号": "样品", "值": "读数"}}`，即标准字段映射到原表头；未列出的字段使用标准表头。CSV 用 `openpt validate input.csv --sheet 均匀性 --encoding utf-8-sig` 检查；GBK 文件须显式指定 `--encoding gbk`。有问题返回码为 1，输入错误返回码为 2。

这是独立的预检查，不会修改输入、不会创建快照。`run`/`review` 也支持 `--columns columns.json`，或用 `--unit mg --encoding utf-8-sig --csv-sheet 均匀性` 导入单测量表 CSV。CSV 的工作表名是所选类型，列号和行号对应原文件；项目名称可通过 `--project` 指定。检查包括测量表、报告声称值、候选批次、指定数值配置及部分数据结构；不能替代实验设计审查。均匀性和稳定性支持长表及宽表，多个被测量可在“被测量配置”中分别登记单位和方法参数；多被测量的参加者结果尚不支持混合导入。选填工作表缺失时以内存空表处理。公式即使有缓存，现有计算器仍不接受；原始输入和列映射会保存到运行快照。

## 随机抽样

`openpt sample --units 100 --pick 20 --seed 42 --output sample-output` 创建新目录，输出 JSON、CSV 和 XLSX；默认每单元生成两次重复的随机检测顺序。可通过 `--strata strata.json` 指定完整分层，例如 `{"层A": [1, 2], "层B": [3, 4]}`（须覆盖 1 至总体数且不得重复）。抽样数不足 10 时提示 `DESIGN_WARNING`；重复测试实际独立取样仍须由人员保证。JSON 保留完整映射和种子，因此盲码不构成身份保密措施；CSV 的危险开头层名会加单引号防公式注入，原始层名保存在 JSON。可用 `run`/`review --sample-record` 把抽样 JSON 作为原始输入一并快照，算法细节见 ADR-003。

## 可追溯工作流

`openpt run input.xlsx --runs-dir runs` 或 `openpt review input.xlsx --runs-dir runs` 会创建新的运行目录，保存原始输入字节、配置、环境、结果、DOCX、日志及哈希清单；默认运行目录根为当前目录的 `runs/`。`--sample-record sample-output/sample.json` 可附带抽样记录。默认输出仅在新运行目录；仅显式指定 `--docx`、`--json` 等路径时另存副本，普通输出不能写进已有运行目录。

`openpt reproduce 运行目录` 首先核验清单，再重新计算并逐字段比较；环境不同会警告。`openpt pack 运行目录 -o 新文件.zip` 打包，`openpt verify 新文件.zip` 检查清单；不解压或执行包内代码，也不覆盖已有 ZIP。清单格式为 `{"files": {"相对文件名": "小写 SHA-256"}}`，清单本身不列入 `files`。清单没有数字签名，攻击者同时修改清单与内容时无法验证真实性；应通过可信渠道独立保存 ZIP 哈希或使用外部签名。每次运行同时生成 DOCX、XLSX 和内联样式 HTML。`openpt decide 运行目录 --item 均匀性 --decision 接受 --by 复核人 --note 备注` 会追加决定并生成新的带序号计算书，不改原始输入和旧计算书；这是运行目录追加写入的明确例外。决定追加后会更新清单，若中途失败导致清单不一致须人工恢复。软件不自动放行。虚构演示可执行 `python examples/trace_workflow.py 新目录`；`examples/trace_run/` 为一份已生成的样例。

## 配置与边界

各统计判据比较统一采用相对容差 `1e-12`，容差内视为相等；原始计算值不修约。真实差异若落入容差范围也会视为边界，须人工复核；具体比较及严格不等式处理见 ADR-002。

方法配置表 `alpha` 默认 0.05；`sigma` 缺省时相应提示未评价；`gl003_hom_criterion` 可选 `f_test`（默认）、`ss_0.3sigma` 或 `both`，旧配置 `strict_homogeneity=TRUE` 等同 `both`；`stability_method` 默认 `two_sample`，可设 `one_sample` 并提供 `reference`；`assigned` 和 `sigma_pt` 用于 z；未提供 `sigma_pt` 时回退到 `sigma`。稳定性推荐模型使用包装单元均值。算法 A 的 `algorithm_a_rule` 默认 `gl002`（尺度第三有效位及均值对应位），可选 `gbt28043`（依据 GB/T 28043-2019 C.3.1，对均值和尺度各自按三位有效数字比较）、`absolute`（使用 `algorithm_a_tolerance`）或 `simplified`；可配置 `algorithm_a_max_iterations`。`gbt28043` 的有效数字比较采用十进制半偶舍入，不因选择均匀性/稳定性模式而自动切换，零初值替代仍须人工审核。采用参加者稳健公议值时，指定值和其不确定度使用与所显示算法 A 相同的规则、容差及迭代上限；程序另算绝对容差收敛对照并放入计算书附录，显示位数不同时提示停止规则敏感。DOCX 参加者 z 值默认保留两位小数，配置 `display_z_decimals` 可设 0～12 位；CSV 和 JSON 不按此设置截断。不平衡均匀性方法及分位数定义见 ADR-002。相关和配对稳定性设计必须在模板中显式声明，程序将阻断结论；参考值不确定度不可忽略时亦须显式声明并阻断。程序不能自动判定设计独立性。全部重复值仅用于复核，常规运行不接受。

封闭内测可在方法配置设置 `criterion_standard=gbt28043`（默认 `gl003`）。GB/T 均匀性常规模式需要平衡且每样至少两次重复，不能重复时可显式选择 `single`；稳定性各组可为单次测量，仍计算基本均值差判据，但该组的组内重复性标为不可评价；`gbt_hom_rule` 与 `gbt_stability_rule` 应于试验前分别选择 `basic`（默认）或 `extended`，预选判据为主结论，另一判据和 GL003 计算仅供参考。选中扩展判据但缺少必要输入或超出系数适用范围时，主结论为未评价，不自动回退。均匀性扩展系数仅在表 B.1 的样品数范围内计算；方法重复性、实验顺序和离群值均需人工审核，程序不自动剔除。稳定性显示各组组内重复性与 0.5σ_pt 的比较；超过时按 B.4.1.2 提示复核，并非自动合格判据。稳定性扩展判据须手动输入互相独立的两组均值标准不确定度 `stability_u1`、`stability_u2`；缺失时不评价扩展判据。额外时间组不会复用稳定期的 `stability_u2`；可在 `stability_period_options` 逐组登记，如 `{"运输期":{"kind":"transport","u2":0.02}}`。运输组的基线必须由人员确认是未运输对照，`u2` 为该组均值标准不确定度；同一时点不得同时从全局和逐组配置输入 `u2`。`report_standard` 可登记报告模式以提示 `STANDARD_MODE`。在指定值表中，`stability_disposition` 默认为 `pending`；已有时点的预选主判据未通过或未评价时阻断参与者评价。`budgeted` 须登记评定依据，并按涉及的储存或运输时点，将人工评定的影响映射到预算或声明已包含；`reviewed` 须记录书面依据；`withhold` 始终暂停评价。程序不从均值差自动推导不确定度，也不能验证审批和未声明的相关性；重新制备后须使用新数据重算。GB/T 模式仍处开发和验证阶段，未完成全部标准核对，不能用于正式评价；运输条件及不确定度分量的适用性须人工复核。

GB/T 基本判据可按被测量填写 `sigma` 或 `delta_e`；两者均填写时必须用 `gbt_criterion_basis` 明确选择 `sigma_pt` 或 `delta_e`。均匀性和稳定性分别使用 0.3σ_pt 或 0.1δ_E，指定值不确定度提示也使用所选依据。δ_E 与被测量须使用相同单位。δ_E 依据下不将其代入以 σ_pt 表达的扩展判据，选扩展主判据时结果为未评价；重复性检查和 z/z′ 计算仍须提供各自所需的 σ_pt，不从 δ_E 自动推算。

### 指定值和能力统计量

在“指定值与不确定度”表登记方法：`known`、`certified`、`reference`、`expert_consensus`、`participant_consensus`。前四类可输入已评定的值、标准不确定度及各自来源；已知值也可在 `known_components` 中以英文逗号分隔输入互相独立的标准不确定度分量，按平方和开方合成；专家公议也可在 `expert_values` 中输入独立同精度的专家结果，使用算术平均值和样本标准误 s/√n，这些为须事先批准的扩展方法。参加者公议值选择 `robust_mean` 或 `median`，使用扩展方法 u(X)=1.25s*/√p。该公式见 GB/T 28043-2019 7.7.3 式(6)，其对中位数法的具体适用性须专家批准。临时和最终 σ_pt 及确定程序分开登记，最终值优先；没有最终值时计算结果提示临时值。`hom_mapping`、`stab_mapping` 可为 `none`、`assigned`、`sigma_prime`；`both` 和重复计入会触发 `DESIGN_REVIEW` 并阻止参加者评价。基础 u(X) 已含某分量时须如实设置相应 `*_in_base`。内测标准模式可将 `hom_source` 设为 `gbt_ss`，显式引用本次计算的 ss，并选择 `hom_mapping`；此时不能同时手工填写非零 `u_hom`。`u_trans` 可单独登记运输标准不确定度，`trans_mapping=assigned` 可并入指定值不确定度；若基础值或所选稳定性分量已包含运输影响，须分别设置 `trans_in_base` 或 `trans_in_stab`，重复计入会触发审核。非零运输分量既未纳入也未声明已包含时不作评价。程序假定已选分量独立，无法识别未登记的重复计入。

方法配置的 `score_type` 可选 `D`、`D%`、`z`、`zprime`、`zeta`、`En` 或 `all`。参加者表中的 u(x)、U(x)、k 用于 ζ 和 En；指定值表需登记 `U_assigned`、`k_assigned` 及结果间 `independent`。En 按 GL002 使用 k=2；ζ 和 En 仅适用于不相关结果。缺少前提时不作评价。指定值由参加者公议时 z′ 转设计审核。D 和 D% 没有默认满意度判据。`examples/assigned_value_scores.xlsx`、`.json`、`.docx` 均为虚构数据。

“算法S”表填写至少两个标准差或极差和统一自由度 1～10，可获得 GL002 A.3 算法 S 结果及迭代历史。`algorithm_s_stop_rule` 可选 `gl002` 或 `absolute`，后者使用 `algorithm_s_tolerance`；程序另算绝对和相对变化量均不超过 1e-12 的收敛对照，三位有效数字不同则提示 `STOP_RULE_SENSITIVITY`。复核声称值支持 `NIQR`、`u(X)`、`zprime:参加者编号`、`zeta:参加者编号`、`En:参加者编号`；映射 JSON 可将统计量键映射到多个条目字符串组成的数组。批量输出按 `DIFFERENCE`、`NOTE`、`MATCH` 排序并支持筛选。

DOCX 指定中文宋体、西文 Times New Roman，不附带字体；若系统缺字，请安装有授权的相应字体或在文档编辑器中选择已安装的中文字体后重新导出。不同平台排版需逐页检查。

公开仓库不包含历史项目数据；内部材料必须保存在仓库外，设置 `OPENPT_INTERNAL_DIR` 后才运行标记为 internal 的测试。仅将已授权的材料存入该目录。

## 引用与许可

引用软件请参见 `CITATION.cff`。项目代码采用 Apache-2.0，详见 `LICENSE` 和 `NOTICE`；第三方许可及原生运行库限制见 `THIRD_PARTY_LICENSES.md`。
