# SPDX-License-Identifier: Apache-2.0
# 可选独立包比较；包默认数值迭代容差与 GL002 第三有效位规则不同。
if (!requireNamespace('metRology', quietly=TRUE)) stop('未安装 metRology')
d <- read.csv(commandArgs(trailingOnly=TRUE)[[1]])
groups <- split(d$value, d$group)
a <- metRology::algA(d$value)
s <- metRology::algS(vapply(groups, sd, numeric(1)), degfree=1)
info <- packageDescription('metRology')
cat('metRology', info$Version, info$License, '\n', file=stderr())
options(digits=17)
write.table(data.frame(statistic=c('A_x','A_s','S_w'), value=c(a$mu,a$s,s)),
            row.names=FALSE, col.names=TRUE, sep=',', quote=FALSE)
