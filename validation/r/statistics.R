# SPDX-License-Identifier: Apache-2.0
# 独立按 GL002 附录 A.2、A.3 公式实现，未移植 openpt 源码。
# 比较精度采用 ADR-002 的至少两次更新、第三有效位及对应位；R round 使用偶数舍入。
args <- commandArgs(trailingOnly=TRUE)
d <- read.csv(args[[1]])
groups <- split(d$value, d$group)
x <- groups[[1]]; y <- groups[[2]]; all_values <- d$value
one <- t.test(x, mu=0)
pooled <- t.test(x, y, var.equal=TRUE)
welch <- t.test(x, y, var.equal=FALSE)
level <- median(all_values); scale <- 1.483 * median(abs(all_values-level))
for (i in seq_len(1000)) {
  bounded <- pmax(level-1.5*scale, pmin(all_values, level+1.5*scale))
  level_new <- mean(bounded)
  scale_new <- 1.134 * sqrt(sum((bounded-level_new)^2)/(length(bounded)-1))
  if (scale_new == 0) {
    stable <- scale == 0 && level == level_new
  } else {
    digits <- 2-floor(log10(abs(scale_new)))
    stable <- round(scale, digits) == round(scale_new, digits) &&
              round(level, digits) == round(level_new, digits)
  }
  level <- level_new; scale <- scale_new
  if (i >= 2 && stable) break
}
if (i == 1000 && !stable) stop('算法 A 未收敛')
# 演示数据使用每组标准差及自由度 1，适用于每组两次测量。
w <- vapply(groups, sd, numeric(1)); pooled_scale <- median(w)
for (j in seq_len(1000)) {
  bounded_w <- pmin(w, 1.645*pooled_scale)
  next_scale <- 1.097*sqrt(sum(bounded_w^2)/length(w))
  if (next_scale == 0) {
    stable_s <- pooled_scale == 0
  } else {
    digits <- 2-floor(log10(abs(next_scale)))
    stable_s <- round(pooled_scale,digits) == round(next_scale,digits)
  }
  pooled_scale <- next_scale
  if (j >= 2 && stable_s) break
}
if (j == 1000 && !stable_s) stop('算法 S 未收敛')
q7 <- quantile(all_values, c(.25,.5,.75), type=7, names=FALSE)
q6 <- quantile(all_values, c(.25,.5,.75), type=6, names=FALSE)
delta <- mean(x)-mean(y); sigma <- 1.2; ux <- 0.4; uX <- 0.2
values <- c(t_one=abs(unname(one$statistic)), df_one=unname(one$parameter), p_one=one$p.value,
            t_pooled=abs(unname(pooled$statistic)), df_pooled=unname(pooled$parameter),
            p_pooled=pooled$p.value, t_welch=abs(unname(welch$statistic)),
            df_welch=unname(welch$parameter), p_welch=welch$p.value,
            A_x=level, A_s=scale, A_iterations=i, S_w=pooled_scale, S_iterations=j,
            median=q7[2], niqr=0.7413*(q7[3]-q7[1]),
            median_type6=q6[2], niqr_type6=0.7413*(q6[3]-q6[1]),
            z=delta/sigma, zprime=delta/sqrt(sigma^2+uX^2),
            zeta=delta/sqrt(ux^2+uX^2), En=delta/sqrt((2*ux)^2+(2*uX)^2))
options(digits=17)
write.table(data.frame(statistic=names(values), value=values), row.names=FALSE,
            col.names=TRUE, sep=',', quote=FALSE)
