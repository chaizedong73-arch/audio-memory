"""Gather time-bound visual evidence for a single audio chunk, with graceful fallback."""
import datetime as dt
import sqlite3
from pathlib import Path

from notes_maintenance import read


def gather(file, duration, root, indexer=None):
    root = Path(root).resolve()
    result = {'pages': [], 'warnings': [], 'sessionId': None}
    try:
        start = dt.datetime.strptime(Path(file).stem[:15], '%Y%m%d_%H%M%S').timestamp()
    except ValueError:
        result['warnings'].append('音频文件时间无法识别'); return result
    from classroom_mode import enabled
    if not enabled(root):
        result['warnings'].append('未开启上课模式，未读取视觉材料'); return result
    recording = read(root/'out/scene/last-recording.json', {}) or {}
    sid = recording.get('id')
    if not sid or not float(recording.get('startAt', 0)) <= start:
        result['warnings'].append('未找到对应时间的录像'); return result
    end = float(recording.get('endAt') or (start + duration))
    if start > end:
        result['warnings'].append('未找到对应时间的录像'); return result
    result['sessionId'] = sid
    slides = []
    for path in (root/'out/scene/ppt').glob('*/index.json'):
        try:
            slides.extend(x for x in read(path, {}).get('items', []) if x.get('videoSession') == sid and x.get('path'))
        except (ValueError, OSError):
            result['warnings'].append('录像PPT索引不可读取')
    slides.sort(key=lambda x: float(x.get('firstSeenAt', x.get('capturedAt', 0))))
    preceding = [x for x in slides if float(x.get('firstSeenAt', x.get('capturedAt', 0))) <= start]
    selected = (preceding[-1:] if preceding else []) + [x for x in slides if start < float(x.get('firstSeenAt', x.get('capturedAt', 0))) <= start + duration]
    if not selected:
        result['warnings'].append('该音频时段缺少录像PPT画面'); return result
    if indexer is None:
        from ppt_concepts import index_images
        indexer = index_images
    db_path = root/'out/material-index/materials.sqlite3'
    for slide in selected:
        path = Path(slide['path']).resolve()
        if not path.is_relative_to((root/'out/scene/ppt').resolve()) or not path.is_file():
            result['warnings'].append('录像PPT图片缺失'); continue
        entry = {'slideId': slide.get('id'), 'image': str(path), 'ocr': '', 'matches': []}
        try:
            page = indexer([{'path': str(path)}], root, limit=1)[0]
            if page.get('error') or page.get('pending'):result['warnings'].append('录像PPT OCR 未完成')
            else:entry['ocr'] = str(page.get('text', ''))[:3000]
        except Exception as exc:
            result['warnings'].append('录像PPT OCR 不可用: '+str(exc)[:160])
        if db_path.is_file():
            try:
                with sqlite3.connect(f'file:{db_path.as_posix()}?mode=ro', uri=True) as db:
                    rows = db.execute('SELECT note_path,method,score,state FROM ppt_note_candidates WHERE session_id=? AND slide_id=? ORDER BY score DESC LIMIT 3', (sid, slide.get('id'))).fetchall()
                entry['matches'] = [{'path': p, 'method': m, 'score': score, 'state': state} for p,m,score,state in rows]
                for match in entry['matches']:
                    original = Path(match['path'])
                    if match['state'] != 'confirmed' or not original.is_file():continue
                    try: match['ocr'] = str(indexer([{'path':str(original)}], root, limit=1)[0].get('text',''))[:3000]
                    except Exception as exc: result['warnings'].append('已匹配PPT OCR不可用: '+str(exc)[:160])
            except sqlite3.Error:result['warnings'].append('PPT匹配索引不可用')
        if not any(m['state']=='confirmed' for m in entry['matches']):result['warnings'].append('未找到已确认匹配的原始PPT页面')
        result['pages'].append(entry)
    return result
