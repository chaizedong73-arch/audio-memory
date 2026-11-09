import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from material_store import initialize, update_module, register_material, get_material, read_material, ppt_note_candidates


class MaterialStoreTests(unittest.TestCase):
    def test_repeated_initialization_preserves_existing_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = initialize(root)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE existing_user_data(value TEXT)')
                db.execute('INSERT INTO existing_user_data VALUES (?)', ('preserved',))
            update_module('gateway', 'ready', root=root)
            initialize(root)
            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(db.execute('SELECT value FROM existing_user_data').fetchone()[0], 'preserved')
                self.assertEqual(db.execute('SELECT state FROM app_module_status WHERE module_id=?', ('gateway',)).fetchone()[0], 'ready')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM app_schema_migrations').fetchone()[0], 2)

    def test_material_idempotency_and_source_conflict(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            register_material('a', 'audio', 'record/a.wav', 'hash1', {'seconds': 2}, root)
            register_material('a', 'audio', 'record/a.wav', 'hash2', {'seconds': 3}, root)
            self.assertEqual(get_material('a', root)['contentHash'], 'hash2')
            self.assertEqual(get_material('a', root)['metadata']['seconds'], 3)
            with self.assertRaises(ValueError):
                register_material('a', 'audio', 'record/b.wav', 'hash3', {}, root)
            self.assertEqual(get_material('a', root)['source'], 'record/a.wav')
            with self.assertRaises(ValueError):
                register_material('b', 'audio', '../private.wav', 'hash', {}, root)

    def test_read_registered_material_uses_identity_and_confines_source(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as elsewhere:
            root = Path(folder)
            source = root / 'record' / 'sample.wav'
            source.parent.mkdir(); source.write_bytes(b'audio-content')
            register_material('a' * 24, 'audio', 'record/sample.wav', 'hash', {}, root)
            item, content = read_material('a' * 24, root)
            self.assertEqual(content, b'audio-content')
            self.assertEqual(item['kind'], 'audio')
            register_material('b' * 24, 'transcript_segment', 'record/sample.wav', 'hash', {'record': {'text': 'corrected'}}, root)
            self.assertEqual(read_material('b' * 24, root)[1]['text'], 'corrected')
            with self.assertRaises(FileNotFoundError): read_material('c' * 24, root)
            outside = Path(elsewhere) / 'private.wav'; outside.write_bytes(b'private')
            source.unlink()
            try: source.symlink_to(outside)
            except OSError: return
            with self.assertRaises(FileNotFoundError): read_material('a' * 24, root)

    def test_ppt_candidates_reads_only_requested_session_and_orders(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); self.assertEqual(ppt_note_candidates(root, 's', 'p'), [])
            database = initialize(root)
            with closing(sqlite3.connect(database)) as db, db:
                db.execute('CREATE TABLE ppt_note_candidates(session_id TEXT, slide_id TEXT, note_path TEXT, method TEXT, score REAL, state TEXT)')
                db.executemany('INSERT INTO ppt_note_candidates VALUES(?,?,?,?,?,?)', [
                    ('s', 'p', 'one', 'match', .5, 'confirmed'),
                    ('s', 'p', 'two', 'match', .9, 'candidate'),
                    ('other', 'p', 'private', 'match', 1, 'confirmed')])
            result = ppt_note_candidates(root, 's', 'p')
            self.assertEqual([x['path'] for x in result], ['two', 'one'])

    def test_future_schema_is_rejected_without_overwriting(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = initialize(root)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('INSERT INTO app_schema_migrations(version) VALUES (999)')
            with self.assertRaises(RuntimeError): initialize(root)
            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(db.execute('SELECT MAX(version) FROM app_schema_migrations').fetchone()[0], 999)

    def test_upgrade_version_one_preserves_module_status(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'out' / 'material-index' / 'materials.sqlite3'
            path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE app_schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
                db.execute('INSERT INTO app_schema_migrations(version) VALUES (1)')
                db.execute('CREATE TABLE app_module_status(module_id TEXT PRIMARY KEY, state TEXT NOT NULL, detail TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
                db.execute('INSERT INTO app_module_status(module_id,state) VALUES (?,?)', ('gateway','ready'))
            initialize(root)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT state FROM app_module_status').fetchone()[0], 'ready')
                self.assertEqual(db.execute('SELECT MAX(version) FROM app_schema_migrations').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
