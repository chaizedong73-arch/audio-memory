import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from asr_visual_context import gather

class VisualContextTests(unittest.TestCase):
    def test_missing_recording_warns_without_error(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'classroom-mode.json').write_text('{"enabled":true}',encoding='utf-8')
            result=gather('20261030_153650_0001.wav',15,root)
            self.assertFalse(result['pages']); self.assertTrue(result['warnings'])

    def test_visual_context_uses_alternate_material_layout(self):
        from unittest.mock import patch
        from material_exchange import MaterialExchange
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'classroom-mode.json').write_text('{"enabled":true}',encoding='utf-8')
            store=root/'new-store'; scene=store/'scene'; scene.mkdir(parents=True)
            ts=dt.datetime(2026,10,30,15,36,50).timestamp()
            (scene/'last-recording.json').write_text(json.dumps({'id':'s','startAt':ts-30,'endAt':ts+30}),encoding='utf-8')
            slide_dir=scene/'ppt'/'run'; slide_dir.mkdir(parents=True)
            image=slide_dir/'1.png'; image.write_bytes(b'image')
            (slide_dir/'index.json').write_text(json.dumps({'items':[{'id':'p','path':str(image),'videoSession':'s','firstSeenAt':ts-1}]}),encoding='utf-8')
            exchange=MaterialExchange(root,transcripts=store)
            with patch('asr_visual_context.MaterialExchange',return_value=exchange):
                result=gather('20261030_153650_0001.wav',15,root,indexer=lambda items,root,limit:[{'text':'visual','path':items[0]['path']}])
            self.assertEqual(result['pages'][0]['ocr'],'visual')
            self.assertFalse((root/'out').exists())

    def test_recorded_page_is_used_when_original_missing(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'classroom-mode.json').write_text('{"enabled":true}',encoding='utf-8')
            scene=root/'out/scene'; scene.mkdir(parents=True)
            ts=dt.datetime(2026,10,30,15,36,50).timestamp()
            (scene/'last-recording.json').write_text(json.dumps({'id':'s','startAt':ts-30,'endAt':ts+30}),encoding='utf-8')
            folder=scene/'ppt/run'; folder.mkdir(parents=True); img=folder/'1.png'; img.write_bytes(b'image')
            (folder/'index.json').write_text(json.dumps({'items':[{'id':'p','path':str(img),'videoSession':'s','firstSeenAt':ts-1}]}),encoding='utf-8')
            result=gather('20261030_153650_0001.wav',15,root,indexer=lambda items,root,limit:[{'text':'术语','path':items[0]['path']}])
            self.assertEqual(result['pages'][0]['ocr'],'术语'); self.assertTrue(result['warnings'])

if __name__=='__main__': unittest.main()
