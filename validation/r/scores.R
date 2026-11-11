# SPDX-License-Identifier: Apache-2.0
# GL002 4.4.1.3 的四种评分公式；假定调用方已核验独立性等前提。
d <- read.csv(commandArgs(trailingOnly=TRUE)[[1]])
z <- (d$x-d$X)/d$sigma
zp <- (d$x-d$X)/sqrt(d$sigma^2+d$uX^2)
zeta <- (d$x-d$X)/sqrt(d$ux^2+d$uX^2)
en <- (d$x-d$X)/sqrt(d$Ux^2+d$UX^2)
out <- data.frame(id=rep(d$id,each=4),statistic=rep(c('z','zprime','zeta','En'),nrow(d)),
                  value=as.vector(t(cbind(z,zp,zeta,en))))
options(digits=17)
write.table(out,row.names=FALSE,col.names=TRUE,sep=',',quote=FALSE)
