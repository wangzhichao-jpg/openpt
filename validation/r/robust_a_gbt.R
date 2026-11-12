# SPDX-License-Identifier: Apache-2.0
# GB/T 28043-2019 C.3.1 各自三位有效数字停止规则的独立对照。
x <- read.csv(commandArgs(trailingOnly=TRUE)[[1]])$value
m <- median(x); s <- 1.483*median(abs(x-m))
for (i in seq_len(1000)) {
  clipped <- pmax(m-1.5*s,pmin(x,m+1.5*s))
  next_m <- mean(clipped)
  next_s <- 1.134*sqrt(sum((clipped-next_m)^2)/(length(x)-1))
  stable <- i>=2 && signif(m,3)==signif(next_m,3) && signif(s,3)==signif(next_s,3)
  m <- next_m; s <- next_s
  if (stable) break
}
if (i==1000 && !stable) stop('算法 A 未收敛')
v <- c(A_x=m,A_s=s,A_iterations=i)
options(digits=17)
write.table(data.frame(statistic=names(v),value=v),row.names=FALSE,col.names=TRUE,
            sep=',',quote=FALSE)
