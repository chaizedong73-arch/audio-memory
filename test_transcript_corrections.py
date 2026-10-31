import json
from pathlib import Path
import tempfile
import unittest
from transcript_corrections import apply_replacements, record_key, load, save
from annotation_worker import run


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.source = self.root / 'out' / '20261023' / 'timeline.jsonl'
        self.source.parent.mkdir(parents=True)
        self.row = {'file': '20261023_120000_0001', 'start': 43200, 'end': 43215, 'text': '因为我们要找到去谁啊', 't': '12:00:00'}
        self.source.write_text(json.dumps(self.row, ensure_ascii=False)+'\n', encoding='utf-8')
        self.original = self.source.read_bytes(); self.key = record_key(self.source, self.row)
        self.note = {'id': 'one', 'recordId': self.key, 'selected': '去谁', 'selectionStartUtf16': 7, 'selectionLengthUtf16': 2,
                     'instruction': '这里应为区间', 'replacement': '区间', 'baseRevision': 0, 'status': 'submitted', 'batchId': 'batch'}
        self.record = {'id': self.key, 'sourceFile': str(self.source), 'file': self.row['file'], 'start': 43200, 'end': 43215,
                       'original': self.row['text'], 'text': self.row['text'], 'revision': 0}
        save({'schemaVersion': 1, 'records': {self.key: self.record}, 'annotations': [self.note]}, self.root)

    def tearDown(self): self.temp.cleanup()

    def test_direct_correction_is_immediate_durable_and_raw_is_unchanged(self):
        run('batch', self.root, publisher=lambda p: None)
        result = load(self.root)
        self.assertEqual(result['records'][self.key]['text'], '因为我们要找到区间啊')
        self.assertEqual(result['annotations'][0]['status'], 'applied')
        self.assertEqual(self.source.read_bytes(), self.original)
        corrected = json.loads(self.source.with_name('timeline.corrected.jsonl').read_text(encoding='utf-8'))
        self.assertEqual(corrected['text'], '因为我们要找到区间啊')
        run('batch', self.root, publisher=lambda p: None)
        self.assertEqual(load(self.root)['records'][self.key]['revision'], 1)

    def test_overlap_is_not_applied(self):
        state = load(self.root); state['annotations'].append({**self.note, 'id': 'two'})
        save(state, self.root)
        run('batch', self.root, publisher=lambda p: None)
        result = load(self.root)
        self.assertEqual(result['records'][self.key]['text'], self.row['text'])
        self.assertTrue(all(n['status']=='needs_review' for n in result['annotations']))

    def test_concurrent_revision_is_preserved(self):
        def generate(record, notes):
            state = load(self.root); state['records'][self.key]['revision'] = 2
            state['records'][self.key]['text'] = '其他已经确认的修订'; save(state, self.root)
            return {'one': '区间'}, None
        run('batch', self.root, generator=generate, publisher=lambda p: None)
        self.assertEqual(load(self.root)['records'][self.key]['text'], '其他已经确认的修订')
        self.assertEqual(load(self.root)['annotations'][0]['status'], 'needs_review')

    def test_utf16_offsets_preserve_emoji(self):
        text = '😀因为我们要找到去谁啊'
        note = {**self.note, 'selectionStartUtf16': 9}
        self.assertEqual(apply_replacements(text, [note], {'one': '区间'}), '😀因为我们要找到区间啊')

    def test_uncertain_ai_result_is_marked_for_review(self):
        run('batch', self.root, generator=lambda r,n: ({'one':'去谁'}, None), publisher=lambda p: None)
        self.assertEqual(load(self.root)['annotations'][0]['status'], 'needs_review')
        self.assertEqual(load(self.root)['records'][self.key]['revision'], 0)


if __name__ == '__main__': unittest.main()
