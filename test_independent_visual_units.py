import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

import ocr_unit
from material_bridge import sync
from material_store import list_materials
from visual_worker import run_one, scan


class VisualUnitsTests(unittest.TestCase):
    def test_worker_retries_ocr_without_reextracting_video(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); video=root/'record'/'camera'/'v.webm';video.parent.mkdir(parents=True);video.write_bytes(b'video')
            image=root/'out'/'scene'/'ppt'/'page.png';image.parent.mkdir(parents=True);image.write_bytes(b'image')
            index=image.parent/'index.json';index.write_text(json.dumps({'items':[{'path':str(image)}]}),encoding='utf-8')
            calls=[]
            def fail_ocr(args, **kwargs):
                calls.append(Path(args[1]).name)
                return SimpleNamespace(returncode=0,stdout=json.dumps({'index':str(index),'truncated':False})) if args[1].endswith('video_unit.py') else SimpleNamespace(returncode=1,stdout='')
            self.assertEqual(run_one(video,root,fail_ocr)['stage'],'failed')
            self.assertEqual(calls,['video_unit.py','ocr_unit.py'])
            calls.clear()
            def succeed(args, **kwargs):
                calls.append(Path(args[1]).name)
                if args[1].endswith('time_alignment_unit.py'):
                    alignment=root/'alignment.json'; alignment.write_text('{}',encoding='utf-8')
                    return SimpleNamespace(returncode=0,stdout=json.dumps({'output':str(alignment),'warnings':[]}))
                return SimpleNamespace(returncode=0,stdout='{}')
            self.assertEqual(run_one(video,root,succeed)['stage'],'completed')
            self.assertEqual(calls,['ocr_unit.py','time_alignment_unit.py'])
            events=root/'out'/'scene'/'events.jsonl'
            events.parent.mkdir(parents=True,exist_ok=True)
            events.write_text(json.dumps({'event':'record-end','state':'saved','path':str(video.resolve()),'startAt':100})+'\n',encoding='utf-8')
            calls.clear(); arguments=[]
            def refresh(args, **kwargs):
                calls.append(Path(args[1]).name); arguments.extend(args)
                alignment=root/'alignment.json'; alignment.write_text('{}',encoding='utf-8')
                return SimpleNamespace(returncode=0,stdout=json.dumps({'output':str(alignment),'warnings':[]}))
            self.assertEqual(run_one(video,root,refresh)['stage'],'completed')
            self.assertEqual(calls,['time_alignment_unit.py'])
            self.assertEqual(arguments[arguments.index('--video-start')+1],'100')
            self.assertEqual(run_one(video,root,succeed)['stage'],'completed')
            self.assertEqual(calls,['time_alignment_unit.py'])

    def test_ocr_without_classroom_mode_is_available_to_bridge(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); image = root / 'frame.png'; image.write_bytes(b'fixture')
            def fake(paths, directory):
                return [{'path': str(paths[0]), 'text': 'sample text', 'engine': 'test'}]
            result = ocr_unit.run([image], root, fake)
            self.assertEqual(result['completed'], 1)
            self.assertFalse((root / 'classroom-mode.json').exists())
            self.assertEqual(sync(root)['ocr'], 1)
            self.assertEqual(list_materials(root, 'ppt_ocr')['items'][0]['metadata']['text'], 'sample text')

    def test_one_ocr_failure_does_not_discard_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); a = root / 'a.png'; b = root / 'b.png'
            a.write_bytes(b'a'); b.write_bytes(b'b')
            def fake(paths, directory):
                return [{'path': str(paths[0]), 'text': 'ok'}, {'path': str(paths[1]), 'error': 'failed'}]
            result = ocr_unit.run([a,b], root, fake)
            self.assertEqual(result['completed'], 1)
            self.assertEqual(len(result['errors']), 1)
            catalog = json.loads((root / 'out' / 'ppt-concepts' / 'catalog.json').read_text(encoding='utf-8'))
            self.assertIn(str(a.resolve()), catalog['pages']); self.assertNotIn(str(b.resolve()), catalog['pages'])


    def test_scan_recognizes_completed_video_formats_and_skips_partial(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);camera=root/'record'/'camera';camera.mkdir(parents=True)
            for name in ['a.webm','b.mp4','c.MOV','d.mkv','copy.partial.mp4','notes.txt']:(camera/name).write_bytes(b'fixture')
            seen=[]
            with patch('visual_worker.run_one',side_effect=lambda path,_root: seen.append(path.name) or {'stage':'completed'}):
                result=scan(root)
            self.assertEqual(set(seen),{'a.webm','b.mp4','c.MOV','d.mkv'});self.assertEqual(len(result),4)


if __name__ == '__main__': unittest.main()
