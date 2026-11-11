# 阶段性 R 独立对照

当前覆盖范围尚未满足 v0.1-C 施工单，报告不得当成完整验证或发布批准。输入为公开示例及合成数据；内部材料应在独立私有目录中运行，不能复制进本目录。

1. 安装 R 4.3.3 和本项目的测试依赖（含 Hypothesis）；将 Rscript 加入 PATH。可选 `metRology` 通过 R 库路径启用。
2. 执行 `python validation/run_r_crosscheck.py`。脚本分别调用独立 R 代码，写入总报告、分报告及随机数据 CSV。存在严格相对误差差异时退出码为 1；不可用或执行错误不会伪造数据。
3. `random_anova_input.csv` 由 Hypothesis 6.170.15、种子 20261112、`PYTHONHASHSEED=0` 生成；重现需固定 Hypothesis 版本和 Python 环境。脚本会在哈希种子非零时重启随机生成进程。随机输入的哈希供额外核验，数值和比较结果见报告。
4. `r/statistics.R` 和 `r/robust_a.R` 依据 GL002 附录 A 的公式单独编写，不移植 openpt 代码；采用项目 ADR-002 的 GL002 停止规则。`metRology` 有自己的默认数值容差和最大迭代次数，故其结果单独展示、不作相同停止规则下的通过判定。

本机 R 环境安装来源为清华 conda-forge 镜像；所用 micromamba 包为 `micromamba-2.10.0-0.tar.bz2`，SHA-256 `9a97976244929bbae28fb1fae504e74a3e7e6d1932870e3a03321f01b7fbd07b`。R 包从清华 CRAN 获取；可选 metRology 0.9-29-2 许可证为 GPL (>= 2)，不作为运行依赖分发。软件及其依赖的许可仍需发布前审查。

本报告的严格相对误差在零值附近特别敏感：理论零值经 R 线性模型计算出现极小浮点残差时，仍如实列为差异。type 6 仅作为分位数定义的对照参考，不混同 type 7 判定。
