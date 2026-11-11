"""命令行入口。"""
import argparse
import json
import sys
from pathlib import Path
from .io.excel import template, read_workbook
from .core.homogeneity import analyze as homogeneity
from .core.stability import analyze as stability
from .core.robust import algorithm_a
from .report.docx import make_report

def calculate(data):
    cfg=data['config']; alpha=float(cfg.get('alpha') or .05); raw=cfg.get('sigma'); sigma=float(raw) if raw not in (None,'') else None
    if cfg.get('gbt28043_extension'): raise ValueError('GB/T 28043 扩展配置尚未实现')
    result={}
    if data['homogeneity']:
        strict=cfg.get('strict_homogeneity',False)
        if not isinstance(strict,bool): raise ValueError('strict_homogeneity 必须是布尔值')
        result['均匀性']=homogeneity(data['homogeneity'],sigma,alpha,strict)
    groups=data['stability']; method=cfg.get('stability_method') or 'two_sample'
    if groups:
        if '稳定期' not in groups or (method=='two_sample' and '基线' not in groups): raise ValueError('稳定性须指定基线及稳定期组')
        raw=cfg.get('reference'); reference=float(raw) if raw not in (None,'') else None
        result['稳定性']=stability(groups.get('基线'),groups['稳定期'],sigma,alpha,method,reference)
    if data['participants']: result['算法A']=algorithm_a([p['value'] for p in data['participants']])
    if not result: raise ValueError('没有可计算的数据')
    return result

def main(argv=None):
    parser=argparse.ArgumentParser(prog='openpt'); sub=parser.add_subparsers(dest='command',required=True)
    t=sub.add_parser('template'); t.add_argument('output')
    for name in ('run','review'):
        p=sub.add_parser(name); p.add_argument('input'); p.add_argument('--docx',required=True); p.add_argument('--json',required=True)
        if name=='review': p.add_argument('--differences',required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='template': template(args.output); return 0
        data=read_workbook(args.input); result=calculate(data); differences=None
        if args.command=='review':
            from .review.compare import review, write_csv
            differences=review(data,result); write_csv(args.differences,differences)
        Path(args.json).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        make_report(args.docx,data,result,differences)
        return 0
    except (ValueError,TypeError,OSError,KeyError,OverflowError) as exc:
        print(f'错误：{exc}',file=sys.stderr); return 2

if __name__=='__main__': raise SystemExit(main())
