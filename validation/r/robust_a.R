# SPDX-License-Identifier: Apache-2.0
# GL002 附录 A.2/A.4 独立按指南公式编写，不移植 openpt 实现。
x <- read.csv(commandArgs(trailingOnly=TRUE)[[1]])$value
m <- median(x); s <- 1.483*median(abs(x-m))
for (i in seq_len(1000)) {
  clipped <- pmax(m-1.5*s,pmin(x,m+1.5*s))
  next_m <- mean(clipped)
  next_s <- 1.134*sqrt(sum((clipped-next_m)^2)/(length(x)-1))
  if (next_s == 0) {
    stable <- s == 0 && m == next_m
  } else {
    places <- 2-floor(log10(abs(next_s)))
    stable <- round(s,places)==round(next_s,places) && round(m,places)==round(next_m,places)
  }
  m <- next_m; s <- next_s
  if (i>=2 && stable) break
}
if (i==1000 && !stable) stop('算法 A 未收敛')
q7 <- quantile(x,c(.25,.5,.75),type=7,names=FALSE)
q6 <- quantile(x,c(.25,.5,.75),type=6,names=FALSE)
v <- c(A_x=m,A_s=s,A_iterations=i,median=q7[2],niqr=0.7413*(q7[3]-q7[1]),
       median_type6=q6[2],niqr_type6=0.7413*(q6[3]-q6[1]))
options(digits=17)
write.table(data.frame(statistic=names(v),value=v),row.names=FALSE,col.names=TRUE,
            sep=',',quote=FALSE)
