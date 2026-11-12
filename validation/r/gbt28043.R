# SPDX-License-Identifier: Apache-2.0
# 独立对照平衡设计与两组稳定性；输入为含基线及后续组的数值 CSV。
args <- commandArgs(trailingOnly=TRUE)
x <- as.matrix(read.csv(args[1], header=FALSE))
y <- as.matrix(read.csv(args[2], header=FALSE))
sigma <- as.numeric(args[3])
u1 <- as.numeric(args[4]); u2 <- as.numeric(args[5])
delta_e <- if (length(args) >= 6) as.numeric(args[6]) else NA_real_
basis <- if (length(args) >= 7) args[7] else 'sigma_pt'
u_assigned <- if (length(args) >= 8) as.numeric(args[8]) else NA_real_
if (!(basis %in% c('sigma_pt', 'delta_e'))) stop('invalid basis')
basic_limit <- if (basis == 'delta_e') .1*delta_e else .3*sigma
g <- nrow(x); m <- ncol(x)
sx <- sd(rowMeans(x)); sw <- sqrt(mean(apply(x, 1, var))); sw_followup <- sqrt(mean(apply(y, 1, var)))
ss <- sqrt(max(0, sx^2-sw^2/m))
f1 <- qchisq(.95,g-1)/(g-1)
factor <- if (m == 2) (qf(.95,g-1,g)-1)/2 else qf(.95,g-1,g*(m-1))/m
c <- f1*(.3*sigma)^2+factor*sw^2
difference <- abs(mean(x)-mean(y))
values <- c(sx=sx,sw=sw,sw_followup=sw_followup,ss=ss,f1=f1,factor=factor,c=c,extended_limit=sqrt(c),
            difference=difference,stability_limit=.3*sigma+2*sqrt(u1^2+u2^2),
            basic_limit=basic_limit, hom_basic=as.numeric(ss <= basic_limit),
            stability_basic=as.numeric(difference <= basic_limit),
            uncertainty_warning=as.numeric(u_assigned >= basic_limit))
options(digits=17)
write.table(data.frame(statistic=names(values),value=values),row.names=FALSE,sep=',',quote=FALSE,na='NaN')
