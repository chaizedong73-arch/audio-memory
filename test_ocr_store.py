import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
import singlelock
from ocr_store import OcrStore


class OcrStoreTests(unittest.TestCase):
    def test_concurrent_processes_merge_without_losing_catalog_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); lock=singlelock.acquire(str(root/'.locks'/'ocr-catalog.lock'));self.assertIsNotNone(lock)
            code=("import sys;from ocr_store import OcrStore;"
                  "root,name,key=sys.argv[1:];OcrStore(root).commit({name:{'hash':key,'stamp':[1,2]}},{key:{'text':name}})")
            children=[]
            try:
                for name,key in [('first','a'*64),('second','b'*64)]:
                    children.append(subprocess.Popen([sys.executable,'-c',code,str(root),name,key],stdout=subprocess.PIPE,stderr=subprocess.PIPE))
                time.sleep(.3);lock.close();lock=None
                for child in children:
                    stdout,stderr=child.communicate(timeout=20)
                    self.assertEqual(child.returncode,0,stderr.decode('utf-8',errors='replace'))
                store=OcrStore(root);catalog=store.catalog()
                self.assertEqual(set(catalog['pages']),{'first','second'})
                self.assertEqual(store.result('a'*64)['text'],'first')
                self.assertEqual(store.result('b'*64)['text'],'second')
            finally:
                if lock is not None:lock.close()
                for child in children:
                    if child.poll() is None:child.terminate();child.wait(timeout=5)

    def test_corrupt_catalog_is_preserved_and_outside_storage_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as other:
            root=Path(folder);store=OcrStore(root);store.catalog_path.write_text('{broken',encoding='utf-8')
            with self.assertRaises(ValueError):store.commit({'image':{'hash':'a'*64}}, {'a'*64:{'text':'x'}})
            self.assertEqual(store.catalog_path.read_text(encoding='utf-8'),'{broken')
            self.assertFalse((store.folder/('a'*64+'.json')).exists())
            with self.assertRaises(ValueError):OcrStore(root,folder=other)

if __name__=='__main__':unittest.main()
