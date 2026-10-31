import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from transcript_corrections import apply_manual_text, effective, load, publish_reviewed

class ManualCorrectionTests(unittest.TestCase):
    def test_manual_correction_preserves_raw_and_rejects_stale_update(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'out'/'20261031'/'timeline.jsonl';source.parent.mkdir(parents=True)
            raw={'file':'test.wav','start':0,'end':1,'text':'😀试图','t':'10:00:00'}
            source.write_text(json.dumps(raw,ensure_ascii=False)+'\n',encoding='utf-8');original=source.read_bytes()
            version=hashlib.sha256(json.dumps(raw,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            result=apply_manual_text(root,source,1,version,'😀视图')
            self.assertEqual(result,{'changed':True,'revision':1});self.assertEqual(source.read_bytes(),original)
            state=load(root);self.assertEqual(effective(raw,source,state)['text'],'😀视图')
            self.assertEqual(state['annotations'][0]['selectionLengthUtf16'],4)
            with self.assertRaisesRegex(ValueError,'字幕已发生变化'):apply_manual_text(root,source,1,version,'过期覆盖')
            self.assertEqual(effective(raw,source,load(root))['text'],'😀视图')

    def test_outside_source_and_empty_replacement_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);other=root/'timeline.jsonl';other.write_text('{}',encoding='utf-8')
            with self.assertRaises(ValueError):apply_manual_text(root,other,1,'x','文字')
            source=root/'out'/'timeline.jsonl';source.parent.mkdir();source.write_text('{}',encoding='utf-8')
            with self.assertRaises(ValueError):apply_manual_text(root,source,1,'x','  ')


    def test_existing_corrected_file_is_backed_up_before_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'out'/'day'/'timeline.jsonl';source.parent.mkdir(parents=True)
            row={'file':'test.wav','start':0,'end':1,'text':'原稿'}
            source.write_text(json.dumps(row,ensure_ascii=False)+'\n',encoding='utf-8')
            corrected=source.with_name('timeline.corrected.jsonl');corrected.write_text('手工保留内容',encoding='utf-8')
            result=publish_reviewed(source,root)
            backups=list((root/'backups'/'transcript-corrections').glob('*.jsonl'))
            self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_text(encoding='utf-8'),'手工保留内容')
            self.assertEqual(json.loads(result.read_text(encoding='utf-8'))['text'],'原稿')
            publish_reviewed(source,root)
            self.assertEqual(len(list((root/'backups'/'transcript-corrections').glob('*.jsonl'))),1)

if __name__=='__main__':unittest.main()
