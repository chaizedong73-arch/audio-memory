import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from material_store import initialize, update_module, register_material, get_material


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
