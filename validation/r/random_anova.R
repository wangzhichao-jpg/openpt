# SPDX-License-Identifier: Apache-2.0
# 随机输入 CSV 单因子 ANOVA：使用 base R aov/anova 独立计算。
d <- read.csv(commandArgs(trailingOnly=TRUE)[[1]])
out <- lapply(split(d, d$case), function(z) {
  z$group <- factor(z$group)
  a <- anova(aov(value ~ group, data=z))
  n <- as.numeric(table(z$group))
  n0 <- (sum(n) - sum(n^2)/sum(n))/(length(n)-1)
  msb <- a$`Mean Sq`[[1]]; msw <- a$`Mean Sq`[[2]]
  data.frame(case=z$case[[1]], statistic=c('MS_between','MS_within','F','p','n0','Ss'),
             value=c(msb,msw,a$`F value`[[1]],a$`Pr(>F)`[[1]],n0,
                     sqrt(max(0,(msb-msw)/n0))))
})
options(digits=17)
write.table(do.call(rbind,out), row.names=FALSE, col.names=TRUE, sep=',', quote=FALSE)
