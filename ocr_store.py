"""Concurrent-safe storage contract for OCR results and their catalog."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid
import singlelock

_PROCESS_LOCK = threading.Lock()


def _save(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class OcrStore:
    def __init__(self, root, folder=None):
        self.root = Path(root).resolve()
        self.folder = Path(folder).resolve() if folder is not None else self.root / 'out' / 'ppt-concepts'
        if not self.folder.resolve().is_relative_to(self.root): raise ValueError('OCR storage outside data root')
        self.folder.mkdir(parents=True, exist_ok=True)
        self.catalog_path = self.folder / 'catalog.json'

    def catalog(self):
        if not self.catalog_path.resolve().is_relative_to(self.root): raise ValueError('OCR catalog outside data root')
        data = json.loads(self.catalog_path.read_text(encoding='utf-8-sig')) if self.catalog_path.exists() else {'pages': {}}
        if not isinstance(data, dict) or not isinstance(data.get('pages'), dict): raise ValueError('Invalid OCR catalog; preserved without changes')
        return data

    def result(self, key):
        if not isinstance(key, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', key): raise ValueError('invalid OCR identity')
        path = (self.folder / (key + '.json')).resolve()
        if not path.is_relative_to(self.root): raise ValueError('OCR result outside data root')
        try: return json.loads(path.read_text(encoding='utf-8-sig'))
        except FileNotFoundError: return {}

    @contextmanager
    def _locked(self):
        with _PROCESS_LOCK:
            lock_path = (self.root / '.locks' / 'ocr-catalog.lock').resolve()
            if not lock_path.is_relative_to(self.root): raise ValueError('OCR lock outside data root')
            deadline = time.monotonic() + 10
            handle = None
            while handle is None:
                handle = singlelock.acquire(str(lock_path))
                if handle is None:
                    if time.monotonic() >= deadline: raise TimeoutError('OCR catalog is busy')
                    time.sleep(.05)
            try: yield
            finally: handle.close()

    def commit(self, pages, results):
        """Merge updates under a cross-process lock; never replace a corrupt catalog."""
        with self._locked():
            catalog = self.catalog()
            for key, result in results.items():
                if not isinstance(key, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', key): raise ValueError('invalid OCR identity')
                path = (self.folder / (key + '.json')).resolve()
                if not path.is_relative_to(self.root): raise ValueError('OCR result outside data root')
                _save(path, result)
            catalog['pages'].update(pages)
            _save(self.catalog_path, catalog)
