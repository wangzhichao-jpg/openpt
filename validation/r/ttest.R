# SPDX-License-Identifier: Apache-2.0
# 两组观测的独立 base R t 检验；输入单位层级由调用者明确指定。
d <- read.csv(commandArgs(trailingOnly=TRUE)[[1]])
x <- d$value[d$group == 1]; y <- d$value[d$group == 2]
a <- t.test(x,y,var.equal=TRUE); b <- t.test(x,y,var.equal=FALSE)
v <- c(t_pooled=abs(unname(a$statistic)),df_pooled=unname(a$parameter),p_pooled=a$p.value,
       t_welch=abs(unname(b$statistic)),df_welch=unname(b$parameter),p_welch=b$p.value)
options(digits=17)
write.table(data.frame(statistic=names(v),value=v),row.names=FALSE,col.names=TRUE,
            sep=',',quote=FALSE)
