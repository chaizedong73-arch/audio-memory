import json
import tempfile
import unittest
from pathlib import Path
from context_auto import current
from visual_worker import list_tasks


class ModuleStatusContractTests(unittest.TestCase):
    def test_status_is_read_through_owning_modules_and_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);context=root/'out'/'context-auto';context.mkdir(parents=True)
            (context/'state.json').write_text(json.dumps({'status':'ready'}),encoding='utf-8')
            (context/'candidate.json').write_text(json.dumps({'narrative':'fixture'}),encoding='utf-8')
            tasks=root/'out'/'visual-tasks';tasks.mkdir()
            (tasks/'item.json').write_text(json.dumps({'stage':'completed','pages':1,'private':'not exported'}),encoding='utf-8')
            self.assertEqual(current(root)['state']['status'],'ready')
            self.assertEqual(current(root)['candidate']['narrative'],'fixture')
            self.assertEqual(list_tasks(root)['items'],[{'stage':'completed','pages':1}])

    def test_context_file_link_outside_root_is_not_read(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as other:
            root=Path(folder);context=root/'out'/'context-auto';context.mkdir(parents=True)
            outside=Path(other)/'private.json';outside.write_text('{"secret":"value"}',encoding='utf-8')
            try:(context/'state.json').symlink_to(outside)
            except OSError:self.skipTest('filesystem symlinks unavailable')
            self.assertEqual(current(root)['state'],{})

if __name__=='__main__':unittest.main()
