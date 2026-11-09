"""Initialize the existing local material database without replacing user data."""
from __future__ import annotations
from data_location import data_root as default_data_root

import argparse
from contextlib import closing
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMA_VERSION = 2


def database_path(root: Path = ROOT) -> Path:
    root = Path(root)
    path = root / 'out' / 'material-index' / 'materials.sqlite3'
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('material database outside data root')
    return path


def initialize(root: Path = ROOT) -> Path:
    path = database_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS app_schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        latest = db.execute('SELECT MAX(version) FROM app_schema_migrations').fetchone()[0] or 0
        if latest > SCHEMA_VERSION:
            raise RuntimeError('Database schema is newer than this application; no changes were applied')
        if latest < 1:
            db.execute('CREATE TABLE IF NOT EXISTS app_module_status (module_id TEXT PRIMARY KEY, state TEXT NOT NULL, detail TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
            db.execute('INSERT INTO app_schema_migrations(version) VALUES (1)')
        if latest < 2:
            db.execute('CREATE TABLE IF NOT EXISTS app_material_records (material_id TEXT PRIMARY KEY, kind TEXT NOT NULL, source TEXT NOT NULL, content_hash TEXT NOT NULL, metadata_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
            db.execute('INSERT INTO app_schema_migrations(version) VALUES (2)')
    return path


def update_module(module_id: str, state: str, detail: str = '', root: Path = ROOT) -> None:
    if not module_id or len(module_id) > 80 or state not in ('ready', 'unavailable', 'error') or len(detail) > 1000:
        raise ValueError('Invalid module status')
    path = initialize(root)
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute('INSERT INTO app_module_status(module_id,state,detail) VALUES (?,?,?) '
                   'ON CONFLICT(module_id) DO UPDATE SET state=excluded.state, detail=excluded.detail, updated_at=CURRENT_TIMESTAMP',
                   (module_id, state, detail))


def register_material(material_id: str, kind: str, source: str, content_hash: str, metadata: dict, root: Path = ROOT) -> None:
    if not all(isinstance(v, str) and v and len(v) <= 512 for v in (material_id, kind, source, content_hash)):
        raise ValueError('Invalid material fields')
    if source.startswith('/') or '\\' in source or ':' in source or '..' in source.split('/'):
        raise ValueError('Material source must be a project-relative path')
    if not isinstance(metadata, dict):
        raise ValueError('Material metadata must be an object')
    payload = json.dumps(metadata, ensure_ascii=False, sort_keys=True, allow_nan=False)
    if len(payload.encode('utf-8')) > 65536:
        raise ValueError('Material metadata exceeds 64 KiB')
    path = initialize(root)
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT kind, source FROM app_material_records WHERE material_id=?', (material_id,)).fetchone()
        if old is not None and old != (kind, source):
            raise ValueError('Material identity conflicts with an existing source')
        db.execute('INSERT INTO app_material_records(material_id,kind,source,content_hash,metadata_json) VALUES (?,?,?,?,?) '
                   'ON CONFLICT(material_id) DO UPDATE SET content_hash=excluded.content_hash, metadata_json=excluded.metadata_json, updated_at=CURRENT_TIMESTAMP',
                   (material_id, kind, source, content_hash, payload))


def get_material(material_id: str, root: Path = ROOT) -> dict | None:
    path = initialize(root)
    with closing(sqlite3.connect(path, timeout=10)) as db:
        row = db.execute('SELECT material_id,kind,source,content_hash,metadata_json FROM app_material_records WHERE material_id=?', (material_id,)).fetchone()
    if row is None:
        return None
    return dict(zip(('id', 'kind', 'source', 'contentHash', 'metadata'), (*row[:4], json.loads(row[4]))))


def list_materials(root: Path = ROOT, kind: str | None = None, limit: int = 100, offset: int = 0) -> dict:
    if not 1 <= limit <= 1000 or offset < 0:
        raise ValueError('Invalid pagination')
    path = database_path(root).resolve()
    if not path.is_file():
        raise FileNotFoundError('Material database is not initialized')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
        where = ' WHERE kind=?' if kind else ''
        params = (kind,) if kind else ()
        total = db.execute('SELECT COUNT(*) FROM app_material_records' + where, params).fetchone()[0]
        rows = db.execute('SELECT material_id,kind,source,content_hash,metadata_json FROM app_material_records' + where + ' ORDER BY material_id LIMIT ? OFFSET ?', params + (limit, offset)).fetchall()
    items = [dict(zip(('id', 'kind', 'source', 'contentHash', 'metadata'), (*row[:4], json.loads(row[4])))) for row in rows]
    return {'items': items, 'total': total, 'nextOffset': offset + len(items) if offset + len(items) < total else None}


def read_material(material_id: str, root: Path = ROOT) -> tuple[dict, bytes | dict]:
    """Read a registered material by identity, never by a caller-supplied path."""
    item = get_material(material_id, root)
    if item is None:
        raise FileNotFoundError('Material not found')
    base = Path(root).resolve()
    source = (base / item['source']).resolve()
    if not source.is_relative_to(base) or not source.is_file():
        raise FileNotFoundError('Material source unavailable')
    if item['kind'] == 'transcript_segment':
        record = item['metadata'].get('record')
        if not isinstance(record, dict):
            raise ValueError('Transcript record unavailable')
        return item, record
    return item, source.read_bytes()


def latest_classroom_snapshot(root: Path) -> dict:
    """Read a consistent classroom export without exposing database access to consumers."""
    path = database_path(root).resolve()
    if not path.is_file(): raise FileNotFoundError('Material database is not initialized')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
        db.execute('BEGIN')
        session = db.execute('SELECT id,video_hash,start_at,end_at FROM sessions ORDER BY rowid DESC LIMIT 1').fetchone()
        if not session: raise ValueError('SQLite 材料库没有硬桥接会话')
        sid = session[0]
        slides = db.execute('SELECT slide_id,asset_hash,first_seen FROM slides WHERE session_id=? ORDER BY first_seen', (sid,)).fetchall()
        segments = db.execute('SELECT line_no,text,ts,ppt_id,ppt_offset FROM segments WHERE session_id=? ORDER BY line_no', (sid,)).fetchall()
        targets = db.execute('SELECT slide_id,note_path,method,state FROM ppt_note_candidates WHERE session_id=?', (sid,)).fetchall()
        return {'session': session, 'slides': slides, 'segments': segments, 'targets': targets}


def ppt_note_candidates(root: Path, session_id: str, slide_id: str) -> list[dict]:
    path = database_path(root).resolve()
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
        rows = db.execute('SELECT note_path,method,score,state FROM ppt_note_candidates WHERE session_id=? AND slide_id=? ORDER BY score DESC LIMIT 3', (session_id, slide_id)).fetchall()
    return [dict(zip(('path', 'method', 'score', 'state'), row)) for row in rows]


def list_module_status(root: Path = ROOT) -> list[dict]:
    path = database_path(root).resolve()
    if not path.is_file(): raise FileNotFoundError('Material database is not initialized')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
        rows = db.execute('SELECT module_id,state,detail,updated_at FROM app_module_status ORDER BY module_id').fetchall()
    return [dict(zip(('module', 'state', 'detail', 'updatedAt'), row)) for row in rows]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Initialize the local materials database')
    parser.add_argument('--root', type=Path, default=default_data_root())
    args = parser.parse_args()
    print(json.dumps({'database': str(initialize(args.root)), 'schemaVersion': SCHEMA_VERSION}, ensure_ascii=False))
