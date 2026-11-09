"""Explicit user decision; bounded transcript-only replacement, never edit references."""
import argparse,json,time
from pathlib import Path
from notes_maintenance import HERE,read,save
from material_exchange import MaterialExchange
from transcript_corrections import locked,load,save as save_overlay,effective,normalize,record_key,lookup_record,publish_reviewed
from subtitle_maintenance import digest,publish_confirmations

def decide(root,identifier,action,term=''):
 if action not in ('accept','reject'):raise ValueError('确认操作无效')
 with locked(root):
  reviews=read(root/'subtitle-reviews.json',{'items':{}});pair=next(((key,value) for key,value in reviews['items'].items() if value.get('id')==identifier),None)
  if not pair or pair[1].get('status')!='needs_confirmation':raise ValueError('该确认已处理或不存在')
  key,item=pair
  if action=='reject':item.update(status='rejected',updatedAt=time.time());save(root/'subtitle-reviews.json',reviews);publish_confirmations(root,reviews);return
  term=term.strip()
  if not term or len(term)>100 or any(c in term for c in '\r\n'):raise ValueError('请填写单个符号或术语，最多100字')
  source=MaterialExchange(root).transcript_source(item['source'], allow_relocated=True)
  state=load(root);current_rows={}
  for line in source.read_text(encoding='utf-8').splitlines():
   try:row=json.loads(line);current_rows[lookup_record(state,source,row)[0]]=row
   except (ValueError,KeyError):continue
  parts=item['baseParts'];ids={p['id'] for p in parts}
  if any(a.get('recordId') in ids for a in state.get('annotations',[])):raise ValueError('已有人工批注，先处理批注；未覆盖')
  output=[]
  import re
  pattern=re.compile('|'.join(('(?<![A-Za-z0-9_])' if v[0].isascii() and v[0].isalnum() else '')+re.escape(v)+('(?![A-Za-z0-9_])' if v[-1].isascii() and v[-1].isalnum() else '') for v in sorted(item['variants'],key=len,reverse=True)))
  if not any(pattern.search(p['text']) for p in parts):raise ValueError('候选不对应完整术语，未替换')
  for part in parts:
   row=current_rows.get(part['id']);old=state['records'].get(part['id'])
   if not row or normalize(effective(row,source,state)['text'])!=part['text'] or (old.get('revision',0) if old else 0)!=part['revision']:raise ValueError('字幕版本已变化，未应用旧确认')
   text=pattern.sub(lambda m:term,part['text']);output.append(text)
   state['records'][part['id']]={**(old or {}),'id':part['id'],'original':normalize(row['text']),'text':text,'revision':part['revision']+(text!=part['text']),
        'sourceFile':str(source),'file':row['file'],'start':row['start'],'end':row['end'],'reviewer':'human-confirmed'}
  save_overlay(state,root)
  item.update(status='screened',hash=digest('\n'.join(output)),term=term,reviewer='human-confirmed',updatedAt=time.time())
  terms=read(root/'subtitle-terms.json',{'items':[]});entry={'contextKey':item.get('contextKey',''),'term':term,'variants':item['variants'],'confirmedAt':time.time(),'evidence':item.get('reviewEvidence',[])}
  terms['items']=[t for t in terms['items'] if not (t.get('contextKey')==entry['contextKey'] and t.get('term')==term)]+[entry];save(root/'subtitle-terms.json',terms)
  save(root/'subtitle-reviews.json',reviews);publish_confirmations(root,reviews)
 publish_reviewed(source,root)
 from classroom_materials import publish
 publish(source.parent,root=root)

if __name__=='__main__':
 import sys
 parser=argparse.ArgumentParser();source=parser.add_mutually_exclusive_group(required=True);source.add_argument('--request');source.add_argument('--stdin',action='store_true');parser.add_argument('--root',type=Path,default=HERE);args=parser.parse_args();root=args.root.resolve()
 if args.stdin:
  value=json.load(sys.stdin)
 else:
  req=Path(args.request).resolve()
  if req.parent!=(root/'out/subtitle-decisions').resolve():raise ValueError('确认请求位置无效')
  value=read(req)
 decide(root,value['id'],value['action'],value.get('term',''))
 if not args.stdin:req.unlink()
