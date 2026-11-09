"""Local OCR index; preserve exact visual forms, co-occurrence is not semantic equivalence."""
import hashlib,json,re,subprocess,uuid,time
from pathlib import Path
from notes_maintenance import read,save
from ocr_store import OcrStore

def terms(text):
 return list(dict.fromkeys(re.findall(r'[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*|[α-ωΑ-Ω]|[\u4e00-\u9fff]{2,8}',text)))[:250]

def index_images(images,root,ocr=None,limit=12,*,folder=None):
 from classroom_mode import require
 require(root)
 store=OcrStore(root,folder=folder);folder=store.folder;catalog=store.catalog();pending=[];result=[];updates={};stored_results={}
 for image in images:
  p=Path(image['path']);stamp=[p.stat().st_size,p.stat().st_mtime_ns];old=catalog['pages'].get(str(p),{});key=old.get('hash') if old.get('stamp')==stamp else hashlib.sha256(p.read_bytes()).hexdigest();cached=store.result(key)
  if not cached:pending.append((p,key))
  result.append((p,key,cached));updates[str(p)]={'hash':key,'stamp':stamp}
 if pending:
  batch=pending[:limit]
  if ocr:items=ocr([p for p,_ in batch])
  else:
   token=uuid.uuid4().hex;inp=folder/(token+'.input.json');out=folder/(token+'.output.json');save(inp,[str(p) for p,_ in batch])
   try:
    proc=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_name('ppt_ocr.ps1')),'-InputFile',str(inp),'-OutputFile',str(out)],capture_output=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
    if proc.returncode:raise RuntimeError('本地PPT字符提取失败：'+proc.stderr.decode('utf-8',errors='replace')[-500:])
    items=read(out,[])
   finally:
    inp.unlink(missing_ok=True);out.unlink(missing_ok=True)
  for item in items:
   pair=next(((p,key) for p,key in batch if str(p)==item.get('path')),None)
   if pair:
    p,key=pair;item.update(hash=key,terms=terms(item.get('text','')),indexedAt=time.time());stored_results[key]=item
 store.commit(updates,stored_results)
 return [{**(store.result(key) or {'pending':True}),'path':str(p),'hash':key} for p,key,_ in result]

def retrieve(pages,text,limit=4):
 query=terms(text);scores=[]
 for page in pages:
  body=page.get('text','');score=sum(3 if q in page.get('terms',[]) else 1 for q in query if q.lower() in body.lower())
  scores.append((score,page))
 return [dict(path=p['path'],hash=p['hash'],text=p.get('text','')[:2200],terms=p.get('terms',[])[:80],pending=p.get('pending',False),error=p.get('error',''),relation='same-page co-occurrence, not semantic identity') for _,p in sorted(scores,key=lambda x:x[0],reverse=True)[:limit]]
