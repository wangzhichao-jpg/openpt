# SPDX-License-Identifier: Apache-2.0
# 独立采用 base R aov/anova；不移植 openpt 代码。
args <- commandArgs(trailingOnly = TRUE)
d <- read.csv(args[[1]])
d$group <- factor(d$group)
a <- anova(aov(value ~ group, data=d))
n <- as.numeric(table(d$group))
n0 <- (sum(n)-sum(n*n)/sum(n))/(length(n)-1)
msb <- a$`Mean Sq`[[1]]
msw <- a$`Mean Sq`[[2]]
values <- c(MS_between=msb, MS_within=msw, F=a$`F value`[[1]],
            p=a$`Pr(>F)`[[1]], n0=n0, Ss=sqrt(max(0,(msb-msw)/n0)))
options(digits=17)
write.table(data.frame(statistic=names(values), value=values), row.names=FALSE,
            col.names=TRUE, sep=",", quote=FALSE)
