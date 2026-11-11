"""GL003 5.2/5.3；重复值模型仅供复核。"""
import math
import numpy as np
from scipy.stats import t as t_distribution

def _observations(data, pooled_repeats):
    try: a=np.asarray(data,dtype=float)
    except (ValueError,TypeError): raise ValueError('稳定性数据须为数值矩阵') from None
    if a.ndim!=2 or a.shape[0]<2 or a.shape[1]<1 or not np.isfinite(a).all(): raise ValueError('稳定性至少需要两个单元及有限数值')
    return a.ravel() if pooled_repeats else a.mean(axis=1)

def summary_t(mean1,mean2,s1,s2,n1,n2,alpha=0.05,welch=False):
    if n1<2 or n2<2 or min(s1,s2)<0 or not all(math.isfinite(x) for x in (mean1,mean2,s1,s2,alpha)) or not 0<alpha<1: raise ValueError('t 检验参数无效')
    a,b=s1*s1/n1,s2*s2/n2
    if welch:
        se=math.sqrt(a+b); denom=a*a/(n1-1)+b*b/(n2-1); df=(a+b)**2/denom if denom else None
    else:
        df=n1+n2-2; se=math.sqrt(((n1-1)*s1*s1+(n2-1)*s2*s2)/df*(1/n1+1/n2))
    difference=abs(mean1-mean2); t=difference/se if se else None
    if t is not None and not math.isfinite(t): t=None
    critical=float(t_distribution.ppf(1-alpha/2,df)) if df else None
    return {'t':t,'df':df,'p':float(2*t_distribution.sf(t,df)) if t is not None and df else None,'critical':critical,'pass':t<critical if t is not None and critical else None,'difference':difference,'se':se,'s1':s1,'s2':s2,'mean1':mean1,'mean2':mean2,'n1':n1,'n2':n2,'status':'OK' if t is not None else 'INDETERMINATE'}

def analyze(baseline, followup, sigma=None, alpha=.05, method='two_sample', reference=None, model='unit_pooled'):
    if model not in ('unit_pooled','repeats_pooled','repeats_welch'): raise ValueError('未知稳定性模型')
    if method not in ('one_sample','two_sample'): raise ValueError('未知稳定性方法')
    if not 0<alpha<1: raise ValueError('alpha 无效')
    if sigma is not None and (not math.isfinite(sigma) or sigma<=0): raise ValueError('sigma 无效')
    y=_observations(followup,model!='unit_pooled')
    if method=='one_sample':
        if reference is None or not math.isfinite(reference): raise ValueError('单样本检验需要参考值')
        n=len(y); mean=float(y.mean()); sd=float(y.std(ddof=1)); se=sd/math.sqrt(n); diff=abs(mean-reference); t=diff/se if se else None; df=n-1; crit=float(t_distribution.ppf(1-alpha/2,df))
        result={'t':t,'df':df,'p':float(2*t_distribution.sf(t,df)) if t is not None else None,'critical':crit,'pass':t<crit if t is not None else None,'difference':diff,'se':se,'s1':sd,'mean1':mean,'reference':reference,'n1':n,'status':'OK' if t is not None else 'INDETERMINATE'}
    else:
        x=_observations(baseline,model!='unit_pooled')
        result=summary_t(float(x.mean()),float(y.mean()),float(x.std(ddof=1)),float(y.std(ddof=1)),len(x),len(y),alpha,model=='repeats_welch')
    result.update({'model':model,'method':method,'threshold':0.3*sigma if sigma is not None else None,'mean_difference_pass':result['difference']<=0.3*sigma if sigma is not None else None,'mean_difference_status':'OK' if sigma is not None else 'NOT_EVALUATED','warnings':[]})
    if len(followup)<6 or (method=='two_sample' and len(baseline)<6):
        result['warnings'].append('GL003 5.2 建议每组不少于6个观测单元')
        if result['status']=='OK': result['status']='DESIGN_WARNING'
    return result
