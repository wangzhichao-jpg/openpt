"""计算书：全部结果以统一 JSON 数值为基础。"""
import json
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn

def make_report(path, data, result, differences=None):
    doc=Document(); style=doc.styles['Normal']; style.font.name='Noto Sans CJK SC'; style._element.rPr.rFonts.set(qn('w:eastAsia'),'Noto Sans CJK SC'); style.font.size=Pt(9)
    doc.add_heading('能力验证计算书（原型）',0)
    doc.add_paragraph('仅供人工复核，不替代统计负责人和正式评价。方法：CNAS-GL003:2018 4.2、4.3、5.2、5.3；CNAS-GL002:2018 附录A.2。程序版本 0.0.1。')
    doc.add_heading('项目信息与配置',1)
    for key in ('info','config','sources'):
        doc.add_paragraph(f'{key}：{json.dumps(data.get(key),ensure_ascii=False,allow_nan=False)}')
    for section, values in result.items():
        doc.add_heading(str(section),1)
        if not isinstance(values,dict):
            doc.add_paragraph(json.dumps(values,ensure_ascii=False,allow_nan=False)); continue
        table=doc.add_table(rows=1,cols=2); table.style='Table Grid'
        table.rows[0].cells[0].text='项目'; table.rows[0].cells[1].text='计算值（全精度）'
        for k,v in values.items():
            cells=table.add_row().cells; cells[0].text=str(k); cells[1].text=json.dumps(v,ensure_ascii=False,allow_nan=False)
    if differences is not None:
        doc.add_heading('复核差异清单',1)
        for item in differences: doc.add_paragraph(json.dumps(item,ensure_ascii=False,allow_nan=False))
    doc.add_paragraph('计算人：________________    日期：____________')
    doc.add_paragraph('复核人：________________    日期：____________')
    doc.save(path)
