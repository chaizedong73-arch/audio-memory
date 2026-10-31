"""Hard classroom-session bridge: camera recording + PPT events + transcript -> notes input."""
import argparse, hashlib, json, os, time
from pathlib import Path
import classroom_mode

HERE = Path(__file__).resolve().parent

def read(path, default=None):
    try: return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError): return default

def save(path, value):
    path=Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp'); temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8'); os.replace(temp,path)

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def build(root=HERE, session_id=None):
    root=Path(root); classroom_mode.require(root)
    receipt=read(root/'out/scene/last-recording.json',{}) or {}
    if receipt.get('state')!='saved' or not receipt.get('id') or not receipt.get('path'): raise ValueError('没有已完成的上课模式录像，拒绝生成笔记材料包')
    video=Path(receipt['path'])
    if not video.is_file() or not video.resolve().is_relative_to((root/'record').resolve()): raise ValueError('录像来源无效')
    start,end=float(receipt.get('startAt',0)),float(receipt.get('endAt',0))
    if not end>start: raise ValueError('录像时间范围无效')
    candidates=[]
    for index in (root/'out/scene/ppt').glob('*/index.json'):
        data=read(index,{}) or {}
        items=[x for x in data.get('items',[]) if x.get('videoSession')==receipt['id'] and start<=float(x.get('capturedAt',0))<=end]
        if items: candidates.extend(items)
    if not candidates: raise ValueError('录像期间没有同一 videoSession 的 PPT 关键帧，拒绝交给笔记AI')
    rows=[]; sources=[]
    for timeline in (root/'out').glob('**/timeline.jsonl'):
        picked=[]
        try:
            for line_no,line in enumerate(timeline.read_text(encoding='utf-8').splitlines(),1):
                row=json.loads(line); ts=float(row.get('ts',-1))
                if start<=ts<=end and row.get('text','').strip(): picked.append({'line':line_no,**row})
        except (OSError,ValueError): continue
        if picked: rows.extend(picked); sources.append({'path':str(timeline.resolve()),'hash':digest(timeline),'count':len(picked)})
    if not rows: raise ValueError('录像期间没有带绝对 ts 的字幕，拒绝交给笔记AI')
    slides=sorted(candidates,key=lambda x:float(x.get('capturedAt',0)))
    for row in rows:
        prior=[s for s in slides if float(s.get('firstSeenAt',s.get('capturedAt',0)))<=float(row['ts'])]
        chosen=prior[-1] if prior else slides[0]
        row['pptId']=chosen['id']; row['pptPath']=chosen['path']; row['pptOffsetSeconds']=round(float(row['ts'])-start,3)
    sid=session_id or receipt['id']; folder=root/'out/classroom-bridge'/sid
    package={'schema':'classroom-session-bridge/v1','createdAt':time.time(),'status':'ready_for_notes',
      'classroomMode':True,'video':{'id':sid,'path':str(video.resolve()),'hash':digest(video),'startAt':start,'endAt':end,'mime':receipt.get('mime')},
      'transcriptSources':sources,'slides':[{'id':s['id'],'path':s['path'],'hash':s.get('contentHash'),'firstSeenAt':s.get('firstSeenAt'),'lastSeenAt':s.get('lastSeenAt'),'videoOffsetSeconds':s.get('videoOffsetSeconds')} for s in slides],
      'segments':sorted(rows,key=lambda x:float(x['ts'])),'rules':['only this package may be passed to notes AI','every segment has one PPT anchor','ASR/OCR/visual output remains derived evidence']}
    save(folder/'notes-input.json',package); save(root/'out/classroom-bridge/latest.json',{'sessionId':sid,'path':str((folder/'notes-input.json').resolve()),'status':'ready_for_notes','createdAt':package['createdAt']})
    return package,folder/'notes-input.json'

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=HERE);args=parser.parse_args();package,path=build(args.root);print(json.dumps({'path':str(path),'segments':len(package['segments']),'slides':len(package['slides'])},ensure_ascii=False))
