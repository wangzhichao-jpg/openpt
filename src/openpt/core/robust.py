# SPDX-License-Identifier: Apache-2.0
"""CNAS-GL002:2018 附录 A.2，算法 A。"""
import math
import numpy as np

def algorithm_a(values, tolerance=1e-10, max_iterations=1000, simplified=False):
    try: a=np.asarray(values,dtype=float)
    except (ValueError,TypeError): raise ValueError('参加者结果必须为有限数值') from None
    if a.ndim!=1 or len(a)<2 or not np.isfinite(a).all(): raise ValueError('至少两个有限参加者结果')
    if not math.isfinite(tolerance) or tolerance<=0 or not isinstance(max_iterations,int) or max_iterations<1: raise ValueError('无效迭代参数')
    x=float(np.median(a)); s=float(1.483*np.median(np.abs(a-x))); history=[]; converged=bool(simplified)
    for i in range(0 if simplified else max_iterations):
        clipped=np.clip(a,x-1.5*s,x+1.5*s); nx=float(clipped.mean()); ns=float(1.134*np.std(clipped,ddof=1))
        if not math.isfinite(nx) or not math.isfinite(ns): raise ValueError('数值溢出')
        history.append({'iteration':i+1,'x':nx,'s':ns})
        if abs(nx-x)<=tolerance and abs(ns-s)<=tolerance: x,s=nx,ns; converged=True; break
        x,s=nx,ns
    return {'x':x,'s':s,'u_x':1.25*s/math.sqrt(len(a)),'n':len(a),'iterations':len(history),'converged':converged,'status':'NOT_CONVERGED' if not converged else 'INDETERMINATE' if s == 0 else 'OK','warning':'稳健尺度为零，需检查重复值与分辨力' if s == 0 else None,'simplified':simplified,'tolerance':tolerance,'history':history}
