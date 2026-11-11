# SPDX-License-Identifier: Apache-2.0
"""声称值与模型对照；严格显示位数和末位容差分开。"""
import csv
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from ..core.stability import analyze as stability, summary_t
from ..core.zscore import zscore

def display(value,digits):
    if value is None: return None
    return Decimal(str(value)).quantize(Decimal(1).scaleb(-digits),rounding=ROUND_HALF_UP)

def review(data, result):
    rows=[]; cfg=data['config']; groups=data['stability']
    for claim in data['claims']:
        name=claim['name']; model=claim.get('model') or 'recommended'; rec=None; reproduced=None
        if name in ('F','Ss'):
            rec=result.get('均匀性',{}).get(name); reproduced=rec
        elif name in ('x*','s*'):
            rec=result.get('算法A',{}).get('x' if name=='x*' else 's'); reproduced=rec
        elif name=='t':
            rec=result.get('稳定性',{}).get('t')
            if model in ('repeats_pooled','repeats_welch'):
                reproduced=stability(groups.get('基线'),groups['稳定期'],model=model)['t']
            elif model=='displayed_summary':
                keys=('mean1','mean2','s1','s2','n1','n2')
                if all(cfg.get(k) not in (None,'') for k in keys):
                    reproduced=summary_t(*(float(cfg[k]) if k not in ('n1','n2') else int(cfg[k]) for k in keys))['t']
            elif model=='recommended': reproduced=rec
        elif name.startswith('z:'):
            participant=next((p for p in data['participants'] if p['id']==name[2:]),None)
            if participant and cfg.get('assigned') is not None and cfg.get('sigma') is not None:
                rec=zscore(participant['value'],float(cfg['assigned']),float(cfg['sigma']))['z']; reproduced=rec
        try:
            digits=int(claim['digits']); assert 0<=digits<=12
            match=display(reproduced,digits)==display(claim['value'],digits) if reproduced is not None else None
        except (ValueError,TypeError,InvalidOperation,AssertionError): raise ValueError('报告声称值显示小数位须为0至12的整数') from None
        note = '技术重复仅用于报告模型复现，须核查伪重复及自由度' if model.startswith('repeats') else '按报告修约中间值重算；须核查各中间值' if model=='displayed_summary' else ''
        rows.append({'统计量':name,'声称值':claim['value'],'来源':claim['source'],'按报告模型复现值':reproduced,'按推荐模型重算值':rec,'显示一致':match,'状态':'NOT_EVALUATED' if match is None else 'MATCH' if match else 'DIFFERENCE','评分条目':'3' if name in ('F','Ss','t') else '7/9、8/10','说明':note})
    return rows

def write_csv(path,rows):
    fields=['统计量','声称值','来源','按报告模型复现值','按推荐模型重算值','显示一致','状态','评分条目','说明']
    with open(path,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
