"""Export the verified local material index to MiniOB-compatible SQL (no media blobs)."""
from data_location import data_root as default_data_root
import argparse
from material_store import latest_classroom_snapshot
from pathlib import Path

HERE=Path(__file__).resolve().parent
def esc(value): return str(value or '').replace("'","''").replace('\n',' ')[:3500]
SCHEMA='''-- MiniOB classroom material mirror. Paths/hashes only; media remains on disk.
CREATE TABLE courses (course_id char(64), notes_root char(1024), material_root char(1024), binding_state char(32));
CREATE TABLE sessions (session_id char(64), course_id char(64), video_hash char(64), start_at float, end_at float, status char(32));
CREATE TABLE slides (session_id char(64), slide_id char(64), source_ppt_hash char(64), page_no int, frame_hash char(64), appeared_at float, match_state char(32));
CREATE TABLE segments (session_id char(64), line_no int, ts float, slide_id char(64), text char(4096), align_state char(32));
CREATE TABLE note_targets (session_id char(64), slide_id char(64), note_path char(2048), match_method char(32), state char(32));
CREATE INDEX idx_sessions_course ON sessions (course_id);
CREATE INDEX idx_slides_session_page ON slides (session_id, page_no);
CREATE INDEX idx_segments_session_ts ON segments (session_id, ts);
CREATE INDEX idx_note_targets_slide ON note_targets (session_id, slide_id);
'''
QUERY='''-- Only this query is a legal input to a notes agent.
SELECT s.text, p.page_no, n.note_path
FROM segments s, slides p, note_targets n
WHERE s.session_id=p.session_id AND s.slide_id=p.slide_id
  AND p.session_id=n.session_id AND p.slide_id=n.slide_id
  AND s.align_state='passed' AND p.match_state='passed' AND n.state='confirmed';
'''
def export(root=HERE, course_id='UNBOUND_COURSE'):
 root=Path(root); out=root/'out/miniob-material-db';out.mkdir(parents=True,exist_ok=True)
 snapshot=latest_classroom_snapshot(root); sid,vhash,start,end=snapshot['session']; lines=[SCHEMA, "INSERT INTO courses VALUES ('%s','','','unbound');"%esc(course_id), "INSERT INTO sessions VALUES ('%s','%s','%s',%s,%s,'blocked_unbound_course');"%(esc(sid),esc(course_id),esc(vhash),start,end)]
 slides=snapshot['slides']
 for no,(slide,h,seen) in enumerate(slides,1):lines.append("INSERT INTO slides VALUES ('%s','%s','',%d,'%s',%s,'passed');"%(esc(sid),esc(slide),no,esc(h),seen or 0))
 for line_no,text,ts,slide,_ in snapshot['segments']:
  lines.append("INSERT INTO segments VALUES ('%s',%d,%s,'%s','%s','passed');"%(esc(sid),line_no,ts or 0,esc(slide),esc(text)))
 for slide,path,method,state in snapshot['targets']:
  lines.append("INSERT INTO note_targets VALUES ('%s','%s','%s','%s','%s');"%(esc(sid),esc(slide),esc(path),esc(method),esc(state)))
 (out/'schema-and-seed.sql').write_text('\n'.join(lines)+'\n',encoding='utf-8');(out/'notes-gate.sql').write_text(QUERY,encoding='utf-8')
 (out/'README.md').write_text('# MiniOB 课堂材料库导入包\n\n当前导出为 `UNBOUND_COURSE`，因为原始 PPT 与 Obsidian 笔记尚未完成课程注册；`notes-gate.sql` 因而必定返回空集。这是硬门槛，不是故障。将 SQL 导入实际 MiniOB 后，先登记课程、原始PPT哈希与已确认笔记目标，才允许查询交给笔记AI。\n',encoding='utf-8')
 return out,len(slides)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=default_data_root());p.add_argument('--course-id',default='UNBOUND_COURSE');a=p.parse_args();out,count=export(a.root,a.course_id);print(f'{out} slides={count}')
