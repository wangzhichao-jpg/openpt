# 全部相同数据的退化 ANOVA

10 个样品每个两次均为 10。理论组间及组内均方均为零，F 为 0/0；openpt 将其标记不可判定。R `aov` 线性模型可能因舍入给出非零极小均方和有限 F，其自身同时警告近乎完美拟合时 F 检验不可靠。该差异须保留，不能用 R 的数值当作可判定结果。

- openpt：状态 `INDETERMINATE`，F=None，p=None。
- R：MS_between=8.7064986152605705e-30，MS_within=8.7064986152605803e-30，F=1，p=0.495390219907834。
- R 原始警告：`Warning message:
In anova.lm(aov(value ~ group, data = d)) :
  ANOVA F-tests on an essentially perfect fit are unreliable`。
