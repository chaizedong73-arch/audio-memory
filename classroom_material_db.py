"""Build a local SQLite index from hard-bridged classroom packages; no AI discovery."""
from data_location import data_root as default_data_root
from material_exchange import MaterialExchange
from material_store import database_path
from contextlib import closing
import argparse, hashlib, json, sqlite3
from pathlib import Path
from PIL import Image

HERE=Path(__file__).resolve().parent
IMAGE={'.png','.jpg','.jpeg','.webp'}

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def dhash(path):
 with Image.open(path) as im:
  im=im.convert('L').resize((9,8)); px=list(im.getdata())
 return ''.join('1' if px[y*9+x]>px[y*9+x+1] else '0' for y in range(8) for x in range(8))
def distance(a,b):return sum(x!=y for x,y in zip(a,b))
SCHEMA='''
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, package_path TEXT NOT NULL, video_path TEXT NOT NULL, video_hash TEXT NOT NULL, start_at REAL, end_at REAL);
CREATE TABLE IF NOT EXISTS assets(hash TEXT PRIMARY KEY, path TEXT NOT NULL, kind TEXT NOT NULL, dhash TEXT, width INTEGER, height INTEGER);
CREATE TABLE IF NOT EXISTS slides(session_id TEXT, slide_id TEXT, asset_hash TEXT, first_seen REAL, last_seen REAL, video_offset REAL, PRIMARY KEY(session_id,slide_id));
CREATE TABLE IF NOT EXISTS segments(session_id TEXT, line_no INTEGER, text TEXT, ts REAL, ppt_id TEXT, ppt_offset REAL, PRIMARY KEY(session_id,line_no));
CREATE TABLE IF NOT EXISTS note_assets(path TEXT PRIMARY KEY, hash TEXT NOT NULL, dhash TEXT NOT NULL, width INTEGER, height INTEGER);
CREATE TABLE IF NOT EXISTS ppt_note_candidates(session_id TEXT, slide_id TEXT, note_path TEXT, method TEXT, score REAL, state TEXT NOT NULL, PRIMARY KEY(session_id,slide_id,note_path));
'''
def asset(db,path,kind):
 path=Path(path).resolve()
 if not path.is_file():raise ValueError('材料缺失：'+str(path))
 h=sha(path); w=he=None; ph=None
 if path.suffix.lower() in IMAGE:
  with Image.open(path) as im:w,he=im.size
  ph=dhash(path)
 db.execute('INSERT OR REPLACE INTO assets VALUES(?,?,?,?,?,?)',(h,str(path),kind,ph,w,he));return h,ph,w,he
def build(root=HERE,notes_root=None):
 root=Path(root); exchange=MaterialExchange(root); package_path,package=exchange.classroom_package()
 if package.get('schema')!='classroom-session-bridge/v1':raise ValueError('课堂包协议不匹配')
 db_path=database_path(root);db_path.parent.mkdir(parents=True,exist_ok=True)
 with closing(sqlite3.connect(db_path)) as db:
  db.executescript(SCHEMA)
  with db:
   sid=package['video']['id'];db.execute('DELETE FROM slides WHERE session_id=?',(sid,));db.execute('DELETE FROM segments WHERE session_id=?',(sid,));db.execute('DELETE FROM ppt_note_candidates WHERE session_id=?',(sid,))
   video=exchange.resolve_material(package['video']['path'],package['video']['hash'])
   db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?,?,?,?)',(sid,str(package_path.resolve()),str(video),package['video']['hash'],package['video']['startAt'],package['video']['endAt']))
   slides=[]
   for s in package['slides']:
    h,ph,w,he=asset(db,exchange.resolve_material(s['path'],s.get('hash')),'recorded_ppt_slide');slides.append((s,h,ph));db.execute('INSERT INTO slides VALUES(?,?,?,?,?,?)',(sid,s['id'],h,s.get('firstSeenAt'),s.get('lastSeenAt'),s.get('videoOffsetSeconds')))
   for n,row in enumerate(package['segments'],1):db.execute('INSERT INTO segments VALUES(?,?,?,?,?,?)',(sid,n,row.get('text',''),row.get('ts'),row.get('pptId'),row.get('pptOffsetSeconds')))
   notes=[]
   if notes_root:
    nr=Path(notes_root).resolve()
    for p in nr.rglob('*'):
     if p.is_file() and p.suffix.lower() in IMAGE:
      h,ph,w,he=asset(db,p,'note_ppt_image');db.execute('INSERT OR REPLACE INTO note_assets VALUES(?,?,?,?,?)',(str(p),h,ph,w,he));notes.append((p,h,ph))
    for s,h,ph in slides:
     for p,nh,nph in notes:
      d=distance(ph,nph); exact=h==nh
      if exact or d<=12:db.execute('INSERT INTO ppt_note_candidates VALUES(?,?,?,?,?,?)',(sid,s['id'],str(p),'sha256' if exact else 'dhash',1.0 if exact else round(1-d/64,4),'confirmed' if exact else 'candidate'))
   counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('sessions','assets','slides','segments','note_assets','ppt_note_candidates')}
 return db_path,counts

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=default_data_root());p.add_argument('--notes-root',type=Path);a=p.parse_args();path,counts=build(a.root,a.notes_root);print(json.dumps({'database':str(path),'counts':counts},ensure_ascii=False))
