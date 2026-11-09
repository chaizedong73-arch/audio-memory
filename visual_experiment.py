"""One manually launched run -> lossless experiment record and a readable ledger."""
import datetime,json,os,time
from pathlib import Path

def catalog(root):
 p=Path(root)/'visual-models/catalog.json'
 return json.loads(p.read_text(encoding='utf-8')).get('catalog',[]) if p.exists() else []

def local_choices(root):
 return [{'id':r['id'],'label':r['label']+' · '+('已下载' if r.get('ready') else '下载中/未就绪'),
  'local':True,'task':r['task'],'ready':r.get('ready',False)} for r in catalog(root) if r['id']!='local:windows']

def validate_suite(root,job):
 if job.get('caseId','unassigned')=='unassigned':return
 suite=json.loads((Path(root)/'visual-experiment-suite.json').read_text(encoding='utf-8'))
 rows=suite.get('cases',[])
 if len(rows)!=3 or {r.get('id') for r in rows}!={'simple','medium','complex'}:raise ValueError('实验必须包含简单、中级、复杂三张用户选图')
 if not all(all(r.get(k) and Path(r[k]).is_file() for k in ('image','ocrGold','visionGold')) for r in rows):raise ValueError('三张图片与两路标准答案尚未备齐，不运行正式测试')
 selected=next((r for r in rows if r['id']==job['caseId']),None)
 if not selected:raise ValueError('未知实验图片')
 from visual_benchmark import pixels
 if pixels(selected['image'])!=pixels(job['image']):raise ValueError('请求图片不属于当前所选实验槽')

def prepare_review(root,run_dir,job):
 if job.get('task')!='vision':return
 suite=json.loads((Path(root)/'visual-experiment-suite.json').read_text(encoding='utf-8'))
 case=next((r for r in suite['cases'] if r['id']==job.get('caseId')),None)
 if not case:return
 gold=json.loads(Path(case['visionGold']).read_text(encoding='utf-8'))
 review={'status':'pending-gpt-review','goldVersion':gold['version'],'goldFile':case['visionGold'],
  'criteria':[{**c,'score':None,'answerEvidence':'','reason':''} for c in gold['criteria']],
  'policy':'由GPT按实际原答逐项核对，保留证据和理由，不运行被测模型'}
 (Path(run_dir)/'graph-evaluation.json').write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf-8')

def submit_review(root,run_dir,criteria):
 root=Path(root);run_dir=Path(run_dir).resolve()
 if not run_dir.is_relative_to((root/'out/visual-vocabulary/runs').resolve()):raise ValueError('评审位置无效')
 path=run_dir/'graph-evaluation.json';review=json.loads(path.read_text(encoding='utf-8'));expected={c['id']:c for c in review['criteria']}
 if len(criteria)!=len(expected) or {c['id'] for c in criteria}!=set(expected):raise ValueError('必须逐项评分，不允许遗漏标准')
 for c in criteria:
  if type(c.get('score')) not in (int,float) or not 0<=c['score']<=expected[c['id']]['weight'] or not c.get('reason'):raise ValueError('评分或理由无效')
 review.update(status='reviewed-by-GPT',criteria=criteria,totalScore=sum(c['score'] for c in criteria),reviewedAt=time.time());path.write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf-8')
 receipt=json.loads((run_dir/'receipt.json').read_text(encoding='utf-8'));record(root,run_dir,json.loads((run_dir/'request.json').read_text(encoding='utf-8')),receipt['result'])

def record(root,run_dir,job,result):
 root=Path(root);run_dir=Path(run_dir);now=datetime.datetime.now().astimezone().isoformat(timespec='seconds')
 receipt={'runId':run_dir.name,'recordedAt':now,'case':job.get('caseId','unassigned'),'model':job.get('model'),
  'task':job.get('task','ocr'),'image':job.get('image'),'result':result,'rawResponse':'raw-response.json' if (run_dir/'raw-response.json').exists() else None}
 (run_dir/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
 # Rebuild from immutable per-run receipts rather than concurrent append writes.
 docs=['# 视觉实验：模型原答与评分','', '每轮由用户手动执行；原始答案保留。自动分数仅辅助，图形关系评分需GPT核对。','']
 for p in sorted((root/'out/visual-vocabulary/runs').glob('*/receipt.json'),key=lambda p:p.stat().st_mtime):
  r=json.loads(p.read_text(encoding='utf-8'));v=r['result'];docs += [f"## {r['recordedAt']} · {r['case']} · {r['model']} · {r['task']}",'',f"运行编号：{r['runId']}；缓存：{v.get('cached',False)}；耗时：{v.get('elapsedSeconds','—')}秒",'']
  if v.get('error'):docs += ['失败：'+v['error'],'']
  else:
   docs += ['### 模型原答','',v.get('rawAnswer',v.get('text','')),'','### 标准化结果（不替代原答）','',json.dumps({'text':v.get('text'),'elements':v.get('elements',[]),'relations':v.get('visualRelations',[])},ensure_ascii=False,indent=2),'']
   q=p.with_name('evaluation.json')
   if q.exists():
    e=json.loads(q.read_text(encoding='utf-8'));docs += [f"文字锚点：{e['exactHits']}/{e['anchorCount']}；这不是总体准确率。",'']
   else:docs += ['自动评分：待标准答案或人工核对。','']
   if v.get('task')=='vision':
    review=p.with_name('graph-evaluation.json')
    if review.exists():
     assessed=json.loads(review.read_text(encoding='utf-8'))
     docs += ['图形评分：'+('待GPT逐条核对' if assessed['status']!='reviewed-by-GPT' else str(assessed['totalScore'])+'/100'),'',json.dumps(assessed,ensure_ascii=False,indent=2),'']
    else:docs += ['图形关系评分：待GPT逐条核对；不以文字召回替代。','']
   if v.get('warnings'):docs += ['格式/完整性提示：'+json.dumps(v['warnings'],ensure_ascii=False),'']
  docs += ['原始文件：'+str(p.parent),'','---','']
 ledger=root/'out/visual-vocabulary/experiment/实验记录.md';ledger.parent.mkdir(parents=True,exist_ok=True)
 stamp=datetime.datetime.now().strftime('%Y-%m-%dT%H:%M');tag=datetime.datetime.now().strftime('%m-%d %H:%M')
 content=f'<!--@SYS {stamp}-->\n'+ '\n'.join(docs)+f'\n〔SYS·{tag}〕\n<!--/@SYS-->\n'
 ledger.write_text(content,encoding='utf-8')
 return str(ledger)

def tolerant_content(content):
 raw=content if isinstance(content,str) else json.dumps(content,ensure_ascii=False)
 try:
  parsed=json.loads(raw.strip().removeprefix('```json').removesuffix('```').strip())
  if isinstance(parsed,dict) and isinstance(parsed.get('text'),str) and isinstance(parsed.get('words'),list):return parsed,raw,False
 except (ValueError,TypeError):pass
 return {'text':raw,'words':[],'elements':[],'relations':[]},raw,True

if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--finalize',required=True);parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent);args=parser.parse_args()
 root=args.root.resolve();target=Path(args.finalize).resolve()
 if not target.is_relative_to((root/'out/visual-vocabulary/runs').resolve()) or target.name!='request.json':raise ValueError('记录路径无效')
 record(root,target.parent,json.loads(target.read_text(encoding='utf-8')),json.loads(target.with_name('result.json').read_text(encoding='utf-8')))
