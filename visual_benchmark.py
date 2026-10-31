"""Score only manually transcribed, image-bound anchors. Never self-grade semantics."""
import hashlib,json,re,time,unicodedata
from pathlib import Path

def pixels(path):
 from PIL import Image
 with Image.open(path) as im:
  im=im.convert('RGB')
  return hashlib.sha256(str(im.size).encode()+im.tobytes()).hexdigest()

def compact(text,fold=False):
 text=re.sub(r'\s+','',unicodedata.normalize('NFC',text))
 return text.casefold() if fold else text

def contains(text,needle,fold=False):
 # Ignore layout whitespace inside an anchor, but retain original word boundaries.
 # Compacting "What time is it" first would falsely reject "What" and "is".
 raw=unicodedata.normalize('NFC',text)
 if fold:raw=raw.casefold()
 positions=[i for i,c in enumerate(raw) if not c.isspace()]
 packed=''.join(raw[i] for i in positions);needle=compact(needle,fold)
 if not needle:return False
 alnum=lambda c:c.isascii() and c.isalnum()
 for match in re.finditer(re.escape(needle),packed):
  start=positions[match.start()];end=positions[match.end()-1]+1
  if alnum(needle[0]) and start and alnum(raw[start-1]):continue
  if alnum(needle[-1]) and end<len(raw) and alnum(raw[end]):continue
  return True
 return False

def score(result,gold):
 # Each field is scored separately: joining them could invent cross-item matches.
 fields=[result.get('text','')]+result.get('text','').splitlines()+[w.get('text','') for w in result.get('words',[])]
 rows=[]
 for a in gold['anchors']:
  exact=any(contains(f,a['text']) for f in fields)
  relaxed=exact or any(contains(f,a['text'],True) for f in fields)
  rows.append(dict(a,status='exact' if exact else 'case-difference' if relaxed else 'missing'))
 hits=sum(r['status']=='exact' for r in rows)
 return {'benchmarkVersion':gold['version'],'scope':'verified textual anchors only; not full-page CER or semantic accuracy',
  'model':result.get('model'),'task':result.get('task','ocr'),'elapsedSeconds':result.get('elapsedSeconds'),
  'usage':result.get('usage',{}),'anchorCount':len(rows),'exactHits':hits,
  'exactRecall':round(hits/len(rows),4) if rows else None,'rows':rows,
  'relationReview':'manual-required' if result.get('task')=='vision' else 'not-applicable',
  'reviewStatus':'assistant-reviewed provisional gold; not user-certified','evaluatedAt':time.time()}

def evaluate(result,image,root,output=None):
 if result.get('task')=='vision':return None
 root=Path(root);gold_path=root/'out/visual-vocabulary/benchmark/outline-gold-v1.json'
 suite=root/'visual-experiment-suite.json'
 if suite.exists():
  for row in json.loads(suite.read_text(encoding='utf-8')).get('cases',[]):
   candidate=Path(row.get('ocrGold') or '__missing__')
   if candidate.is_file():
    check=json.loads(candidate.read_text(encoding='utf-8'))
    if pixels(image)==check.get('pixelHash'):gold_path=candidate;break
 if not gold_path.exists():return None
 gold=json.loads(gold_path.read_text(encoding='utf-8'))
 if pixels(image)!=gold['pixelHash']:return None
 report=score(result,gold)
 if output:
  output=Path(output);output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
  lines=['# 文字锚点核对（暂定标准）','',f"严格命中：{report['exactHits']}/{report['anchorCount']}",
   '仅核对文字覆盖，不代表全文字符准确率；图形关系需人工核验。','', '| 原图文字 | 核对 |','|---|---|']
  labels={'exact':'命中','case-difference':'大小写不同','missing':'未严格命中（可能漏识别、错字或阅读顺序错误）'}
  lines += ['| '+a['text'].replace('|','\\|')+' | '+labels[a['status']]+' |' for a in report['rows']]
  output.with_suffix('.md').write_text('\n'.join(lines),encoding='utf-8')
  summary=[]
  for item in (root/'out/visual-vocabulary/runs').glob('*/evaluation.json'):
   try:
    row=json.loads(item.read_text(encoding='utf-8'))
    if row.get('benchmarkVersion')==gold['version']:
     summary.append({'run':item.parent.name,**{k:row.get(k) for k in ('model','task','exactHits','anchorCount','elapsedSeconds','usage','evaluatedAt')}})
   except (ValueError,OSError):pass
  summary.sort(key=lambda r:r.get('evaluatedAt',0))
  board=root/'out/visual-vocabulary/benchmark/scoreboard.json';board.parent.mkdir(parents=True,exist_ok=True);board.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 return report
