"""Explicit classroom capability boundary; regular recording/subtitle services are independent."""
import json,os,uuid,time,hashlib,shutil
from pathlib import Path

HERE=Path(__file__).resolve().parent
def read(root=HERE):
 try:return json.loads((Path(root)/'classroom-mode.json').read_text(encoding='utf-8-sig'))
 except FileNotFoundError:return {'enabled':False}
def enabled(root=HERE):return read(root).get('enabled') is True
def require(root=HERE):
 if not enabled(root):raise ValueError('请先开启上课模式；视觉词表和笔记AI仅在上课模式运行')
def save(file,value):
 file=Path(file);file.parent.mkdir(parents=True,exist_ok=True)
 temp=file.with_name(file.name+'.'+uuid.uuid4().hex+'.tmp')
 temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temp,file)
def set_enabled(root,value):
 root=Path(root)
 state={'schemaVersion':1,'enabled':bool(value),'generation':uuid.uuid4().hex,'updatedAt':time.time()}
 # Disable the capability before asking a running notes worker to finish.
 save(root/'classroom-mode.json',state)
 if not value:
  file=root/'notes-maintenance.json'
  if file.exists():
   config=json.loads(file.read_text(encoding='utf-8-sig'));config['enabled']=False;save(file,config)
 return state
def snapshot_images(images,root=HERE):
 require(root);folder=Path(root)/'classroom/materials';folder.mkdir(parents=True,exist_ok=True);result=[]
 for item in images:
  source=Path(item['path']).resolve();digest=hashlib.sha256(source.read_bytes()).hexdigest()
  target=folder/(digest+source.suffix.lower())
  if not target.exists():
   temp=target.with_suffix(target.suffix+'.tmp');shutil.copyfile(source,temp);os.replace(temp,target)
  result.append({**item,'sourcePath':str(source),'path':str(target),'imageHash':digest})
 save(folder/'latest-sources.json',result)
 return result
