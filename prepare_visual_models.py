"""Download the explicit experiment shortlist; never run image inference."""
import concurrent.futures,hashlib,json,os,time,urllib.request,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
STORE=ROOT/'visual-models'
MANIFEST=STORE/'catalog.json'

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()

def fetch(row):
 import requests
 p=STORE/row['path'];p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists() and (not row.get('sha256') or sha(p)==row['sha256']):return {'path':row['path'],'bytes':p.stat().st_size,'sha256':sha(p)}
 tmp=p.with_suffix(p.suffix+'.part')
 for attempt in range(3):
  try:
   offset=tmp.stat().st_size if tmp.exists() else 0
   with requests.get(row['url'],headers={'Range':f'bytes={offset}-'} if offset else {},stream=True,timeout=(20,60)) as response:
    response.raise_for_status()
    append=offset>0 and response.status_code==206
    with tmp.open('ab' if append else 'wb') as f:
     for chunk in response.iter_content(1024*1024):f.write(chunk)
   digest=sha(tmp)
   if row.get('sha256') and digest!=row['sha256']:
    tmp.unlink();raise ValueError('SHA256 mismatch')
   os.replace(tmp,p);print('downloaded '+row['path'],flush=True)
   return {'path':row['path'],'bytes':p.stat().st_size,'sha256':digest}
  except Exception:
   if attempt==2:raise
 return {}

def get(url):
 with urllib.request.urlopen(url,timeout=25) as response:return json.load(response)

def load_defaults():
 import yaml, rapidocr
 return yaml.safe_load((Path(rapidocr.__file__).parent/'default_models.yaml').read_text(encoding='utf-8'))['onnxruntime']

def prepare():
 STORE.mkdir(exist_ok=True)
 previous=json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.exists() else {}
 retired=set(previous.get('retiredIds',[]))
 defaults=load_defaults()
 catalog=[{'id':'local:windows','label':'Windows OCR · 系统基线','task':'ocr','kind':'windows','ready':True}];files={}
 variants=[('PP-OCRv4','mobile','ch'),('PP-OCRv4','server','ch'),('PP-OCRv4','server','ch_doc'),('PP-OCRv5','mobile','ch'),('PP-OCRv5','server','ch'),('PP-OCRv6','tiny','multi'),('PP-OCRv6','small','multi'),('PP-OCRv6','medium','multi')]
 for version,size,lang in variants:
  detkey=f'{"multi" if version=="PP-OCRv6" else "ch"}_{version}_det_{size}'
  reckey=f'{lang}_{version}_rec_{size}'
  paths={}
  for task,key in [('det',detkey),('rec',reckey)]:
   meta=defaults[version][task][key];name=meta['model_dir'].rsplit('/',1)[-1];rel='ocr/'+name
   files[rel]={'path':rel,'url':meta['model_dir'],'sha256':meta['SHA256']};paths[task]=str(STORE/rel)
  id='local:ppocr-'+version[-2:].lower()+'-'+size+('-doc' if lang=='ch_doc' else '')
  catalog.append({'id':id,'label':version+' '+size+(' 文档' if lang=='ch_doc' else ''),'task':'ocr','kind':'rapid','version':version,'variant':size,'lang':lang,**paths,'ready':False})
 for repo,model_file,proj,id,label in [
  ('Qwen/Qwen3-VL-2B-Instruct-GGUF','Qwen3VL-2B-Instruct-Q4_K_M.gguf','mmproj-Qwen3VL-2B-Instruct-F16.gguf','qwen3vl2b','Qwen3-VL 2B · Q4_K_M'),
  ('Qwen/Qwen3-VL-4B-Instruct-GGUF','Qwen3VL-4B-Instruct-Q4_K_M.gguf','mmproj-Qwen3VL-4B-Instruct-F16.gguf','qwen3vl4b','Qwen3-VL 4B · Q4_K_M'),
  ('ggml-org/GLM-OCR-GGUF','GLM-OCR-Q8_0.gguf','mmproj-GLM-OCR-Q8_0.gguf','glmocr','GLM-OCR · 文档视觉 Q8')]:
  if 'local-vlm:'+id in retired:continue
  meta=get('https://huggingface.co/api/models/'+repo+'?blobs=true');revision=meta['sha'];siblings={a['rfilename']:a for a in meta['siblings']}
  paths=[]
  for name in [model_file,proj]:
   rel=id+'/'+name;f=siblings[name];files[rel]={'path':rel,'url':f'https://huggingface.co/{repo}/resolve/{revision}/{name}','sha256':f.get('lfs',{}).get('sha256')};paths.append(str(STORE/rel))
  catalog.append({'id':'local-vlm:'+id,'label':label,'task':'vision','kind':'llama','modelFile':paths[0],'projector':paths[1],'source':repo,'revision':revision,'ready':False})
 releases=get('https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=6')
 asset=next(a for release in releases for a in release['assets'] if a['name'].endswith('bin-win-cpu-x64.zip'))
 rel='llama/'+asset['name'];files[rel]={'path':rel,'url':asset['browser_download_url'],'sha256':asset.get('digest','').removeprefix('sha256:') or None}
 # A repeat preparation must not silently reinstall weights the user retired.
 catalog=[row for row in catalog if row['id'] not in retired]
 needed={str(Path(row[k]).resolve()) for row in catalog for k in ('det','rec','modelFile','projector') if row.get(k)}
 files={key:value for key,value in files.items() if str((STORE/key).resolve()) in needed or key.startswith('llama/')}
 status={'state':'downloading','catalog':catalog,'files':[],'errors':[],'updatedAt':time.time(),
  'retiredIds':sorted(retired),'retiredCatalog':previous.get('retiredCatalog',[]),'retiredFiles':previous.get('retiredFiles',[])}
 def persist():
  status['updatedAt']=time.time();tmp=MANIFEST.with_suffix('.tmp');tmp.write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,MANIFEST)
 persist()
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
  jobs={pool.submit(fetch,f):f for f in files.values()}
  for future in concurrent.futures.as_completed(jobs):
   f=jobs[future]
   try:status['files'].append(future.result())
   except Exception as e:status['errors'].append({'path':f['path'],'error':str(e)[:200]});print('FAILED '+f['path'],flush=True)
   persist()
 archive=STORE/rel
 if archive.exists():
  with zipfile.ZipFile(archive) as z:
   for entry in z.infolist():
    dest=(STORE/'llama'/entry.filename).resolve()
    if not dest.is_relative_to((STORE/'llama').resolve()):raise ValueError('zip path outside model directory')
   z.extractall(STORE/'llama')
 executables=list((STORE/'llama').rglob('llama-server.exe'));server=str(executables[0]) if executables else ''
 for row in catalog:
  if row['kind']=='rapid':row['ready']=all(Path(row[k]).exists() for k in ('det','rec'))
  if row['kind']=='llama':row['server']=server;row['ready']=bool(server) and all(Path(row[k]).exists() for k in ('modelFile','projector'))
 status['state']='ready' if not status['errors'] else 'partial';persist();print('PREPARED '+str(sum(r['ready'] for r in catalog))+'/'+str(len(catalog)),flush=True)

if __name__=='__main__':prepare()
