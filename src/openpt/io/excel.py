"""固定模板及来源定位。"""
from pathlib import Path
from collections import defaultdict
from math import isfinite
from openpyxl import Workbook, load_workbook

SHEETS = {
    '项目信息': ['字段', '值'],
    '方法配置': ['字段', '值'],
    '均匀性': ['单元编号', '重复编号', '值', '单位'],
    '稳定性': ['时间组', '单元编号', '重复编号', '值', '单位'],
    '参加者结果': ['参加者编号', '值', '单位'],
    '报告声称值': ['统计量', '声称值', '显示小数位', '来源', '报告模型'],
}

def template(path):
    book = Workbook(); book.remove(book.active)
    for name, headers in SHEETS.items():
        ws = book.create_sheet(name); ws.append(headers); ws.freeze_panes = 'A2'
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = 22
    for row in [('项目名称', ''), ('单位', '')]: book['项目信息'].append(row)
    for row in [('alpha', 0.05), ('sigma', ''), ('strict_homogeneity', False), ('stability_method', 'two_sample'), ('reference', '')]: book['方法配置'].append(row)
    book.save(path)

def read_workbook(path):
    book = load_workbook(Path(path), data_only=False)
    missing = set(SHEETS) - set(book.sheetnames)
    if missing: raise ValueError('缺少工作表：' + ', '.join(sorted(missing)))
    def rows(name):
        ws = book[name]
        if [ws.cell(1, i).value for i in range(1, len(SHEETS[name])+1)] != SHEETS[name]:
            raise ValueError(f'{name}!1 表头错误')
        for cells in ws.iter_rows(min_row=2, max_col=len(SHEETS[name])):
            if not any(c.value is not None for c in cells): continue
            if any(c.data_type == 'f' for c in cells): raise ValueError(f'{name}!{cells[0].row}: 不接受公式')
            yield cells
    info = {str(r[0].value): r[1].value for r in rows('项目信息') if r[0].value}
    config = {str(r[0].value): r[1].value for r in rows('方法配置') if r[0].value}
    if not info.get('项目名称') or not info.get('单位'): raise ValueError('项目信息：项目名称和单位必填')
    def numeric(c, name):
        if isinstance(c.value, bool) or not isinstance(c.value, (int,float)) or not isfinite(c.value):
            raise ValueError(f'{name}!{c.coordinate}: 数值无效')
        return float(c.value)
    def observations(name, stability=False):
        grouped = defaultdict(dict); sources = []
        for r in rows(name):
            group, uid, rep, val, unit = (r[0].value,r[1].value,r[2].value,r[3],r[4].value) if stability else ('均匀性',r[0].value,r[1].value,r[2],r[3].value)
            if not group or uid is None or rep is None: raise ValueError(f'{name}!{r[0].row}: 缺少分组或编号')
            if unit != info['单位']: raise ValueError(f'{name}!{r[-1].coordinate}: 单位不一致')
            key=(str(group),str(uid)); rep=str(rep)
            if rep in grouped[key]: raise ValueError(f'{name}!{r[0].row}: 重复编号')
            grouped[key][rep]=numeric(val,name); sources.append(f'{name}!{val.coordinate}')
        groups = defaultdict(list)
        for (group, uid), values in grouped.items(): groups[group].append(list(values.values()))
        for group, items in groups.items():
            if len({len(x) for x in items}) > 1: raise ValueError(f'{name}: {group} 重复数不平衡')
        return dict(groups), sources
    hom, hs = observations('均匀性'); stab, ss = observations('稳定性', True)
    participants=[]
    for r in rows('参加者结果'):
        if r[0].value is None or r[2].value != info['单位']: raise ValueError(f'参加者结果!{r[0].row}: 编号或单位错误')
        participants.append({'id':str(r[0].value),'value':numeric(r[1],'参加者结果'),'source':f'参加者结果!{r[1].coordinate}'})
    claims=[]
    for r in rows('报告声称值'):
        if r[0].value is None or r[1].value is None or not r[3].value: raise ValueError(f'报告声称值!{r[0].row}: 项目、声称值及来源必填')
        claims.append({'name':str(r[0].value),'value':numeric(r[1],'报告声称值'),'digits':r[2].value,'source':str(r[3].value),'model':r[4].value,'cell':f'报告声称值!{r[1].coordinate}'})
    return {'info':info,'config':config,'homogeneity':hom.get('均匀性',[]),'stability':stab,'participants':participants,'claims':claims,'sources':hs+ss}
