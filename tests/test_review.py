# SPDX-License-Identifier: Apache-2.0
import pytest
from openpt.review.compare import review, write_csv
from openpt.core.stability import analyze

# 合成样例，用于验证两种实验单位及复核分支；并非历史报告。
def test_review_branches(tmp_path):
    x=[[1,2],[2,3],[3,4]]; y=[[2,3],[3,4],[4,5]]
    data={'config':{'assigned':2,'sigma':1}, 'stability':{'基线':x,'稳定期':y},'participants':[{'id':'1','value':3}]}
    data['claims']=[{'name':n,'value':v,'digits':2,'source':'合成数据','model':m} for n,v,m in [('F',1,'recommended'),('Ss',1,'recommended'),('x*',2,'recommended'),('s*',1,'recommended'),('z:1',1,'recommended'),('t',1,'repeats_pooled'),('t',1,'repeats_welch'),('t',1,'unknown')]]
    result={'均匀性':{'F':1,'Ss':1},'算法A':{'x':2,'s':1},'稳定性':analyze(x,y)}
    rows=review(data,result)
    assert len(rows)==8 and rows[0]['状态']=='MATCH' and rows[4]['按推荐模型重算值']==1
    assert rows[-1]['状态']=='NOT_EVALUATED' and '伪重复' in rows[-2]['说明']
    f=tmp_path/'review.csv'; write_csv(f,rows); assert '按报告模型复现值' in f.read_text(encoding='utf-8-sig')
    data['claims'][0]['digits']='bad'
    with pytest.raises(ValueError): review(data,result)
