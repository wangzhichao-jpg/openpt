# SPDX-License-Identifier: Apache-2.0
"""可选的非公开数据验证；数据仅从用户指定的仓库外目录加载。"""
import json
import os
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import pytest
from openpt.core.homogeneity import analyze as hom
from openpt.core.stability import analyze as stab, summary_t
from openpt.core.robust import algorithm_a
from openpt.core.zscore import zscore
from openpt.review.compare import review

pytestmark = pytest.mark.internal

@pytest.fixture
def fixtures():
    value=os.environ.get('OPENPT_INTERNAL_DIR')
    if not value: pytest.skip('未设置内部材料目录')
    return Path(value)/'fixtures'

def load(root,name):
    return json.loads((root/name).read_text(encoding='utf-8'))

def test_homogeneity_stability(fixtures):
    c=load(fixtures,'aliased.json'); x=c['case_a_homogeneity']['data']; y=c['case_a_stability']['data']
    # 来源与页码记录于仓库外 fixtures/aliased.json。
    a=hom(x,.12); assert round(a['F'],2)==1.20 and round(a['Ss'],4)==.0096 and round(a['F_critical'],2)==2.39
    a=stab(x,y); assert round(a['t'],3)==.831 and round(a['s1'],4)==.0236
    s=c['case_a_stability']['displayed_summary']; t=summary_t(s['mean1'],s['mean2'],s['s1'],s['s2'],s['n1'],s['n2'])['t']; assert round(t,4)==.6887 and abs(t-.688)<.001
    x=c['case_b_homogeneity']['data']; a=hom(x,6.61); assert round(a['F'],2)==2.82 and round(a['Ss'],2)==2.07 and a['Ss']>a['threshold']
    a=stab(x,c['case_b_stability_1']['data'],model='repeats_pooled'); assert round(a['t'],3)==.156 and a['df']==24
    a=stab(x,c['case_b_stability_2']['data'],model='repeats_welch'); assert round(a['t'],3)==.984
    assert stab(x,c['case_b_stability_1']['data'])['df']==11

def test_participants(fixtures):
    # 仓库外材料给出来源页码；这里仅核对观察值，不包含报告数据。
    b=load(fixtures,'case_b_participants.json'); a=algorithm_a([float(r[1]) for r in b]); assert len(b)==141 and round(a['x'],1)==88.0 and round(a['s'],2)==3.63
    s=load(fixtures,'case_a_participants.json'); a=algorithm_a([float(r[1]) for r in s]); assert len(s)==32 and round(a['x'],2)==4.99 and round(a['s'],2)==.12
    assert len([zscore(float(r[1]),88.,6.9) for r in b])==141
    # 仓库外 participant 数据来自各报告表格；按显示值精确十进制重算。
    check=lambda rows,X,sigma,q: [(code,(Decimal(value)-Decimal(X))/Decimal(sigma),Decimal(claim)) for code,value,claim in rows]
    assert all(v.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)==claim for _,v,claim in check(b,'88.0','6.9','.01'))
    mismatches=[code for code,v,claim in check(s,'4.99','.12','.1') if v.quantize(Decimal('.1'),rounding=ROUND_HALF_UP)!=claim]
    assert mismatches==['03']

def test_rounded_review(fixtures):
    c=load(fixtures,'aliased.json'); x=c['case_a_homogeneity']['data']; y=c['case_a_stability']['data']; summary=c['case_a_stability']['displayed_summary']
    cfg={k:v for k,v in summary.items() if k!='source'}
    data={'config':cfg,'stability':{'基线':x,'稳定期':y},'participants':[], 'claims':[{'name':'t','value':.688,'digits':3,'source':'内部原始表格','model':'displayed_summary'}]}
    rows=review(data,{'稳定性':stab(x,y)}); r=rows[0]
    assert round(r['按报告模型复现值'],4)==.6887 and not r['显示一致']
    assert '修约中间值' in r['说明'] and 's1=0.025' in r['说明'] and '0.023559' in r['说明']
