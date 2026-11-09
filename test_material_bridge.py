import hashlib
import json
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from material_bridge import sync
from material_store import get_material
from transcript_corrections import record_key
from ai_material_gateway import handler


class BridgeTests(unittest.TestCase):
    def test_bridge_uses_ingestion_contract_without_legacy_directories(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = {'audio': 2, 'transcript': 3, 'errors': []}
            visual = {'slides': 1, 'ocr': 2, 'alignment': 0, 'feedback': 1, 'errors': []}
            with patch('material_ingest.ingest_recordings_and_transcripts', return_value=audio) as first, \
                 patch('material_ingest.ingest_visual_and_feedback', return_value=visual) as second:
                result = sync(root)
            self.assertEqual((result['audio'], result['transcript'], result['slides'], result['feedback']), (2, 3, 1, 1))
            self.assertEqual(result['errors'], [])
            self.assertEqual(first.call_args.args[0], root.resolve())
            self.assertEqual(second.call_args.args[0], root.resolve())
            self.assertFalse((root / 'record').exists())

    def test_feedback_is_indexed_and_readable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler(root))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                request = Request(base + '/v1/feedback', data=b'{"status":"need_more"}', headers={'Content-Type': 'application/json'})
                feedback = json.load(urlopen(request))
                result = sync(root)
                self.assertEqual(result['feedback'], 1)
                indexed = json.load(urlopen(base + '/v1/indexed-materials?kind=feedback'))
                self.assertEqual(indexed['items'][0]['metadata']['record']['id'], feedback['id'])
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_slide_and_full_ocr_are_indexed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); slide = root / 'out' / 'scene' / 'ppt' / 'run' / 'page.png'
            slide.parent.mkdir(parents=True); slide.write_bytes(b'fixture')
            (slide.parent / 'index.json').write_text(json.dumps({'items': [{'id': 'p', 'path': str(slide), 'capturedAt': 1}]}), encoding='utf-8')
            catalog = root / 'out' / 'ppt-concepts'; catalog.mkdir()
            (catalog / 'catalog.json').write_text(json.dumps({'pages': {str(slide): {'hash': 'abc'}}}), encoding='utf-8')
            (catalog / 'abc.json').write_text(json.dumps({'text': 'x' * 1600}), encoding='utf-8')
            result = sync(root)
            self.assertEqual((result['slides'], result['ocr'], result['errors']), (1, 1, []))
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler(root))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                result = json.load(urlopen(f'http://127.0.0.1:{server.server_port}/v1/indexed-materials?kind=ppt_ocr'))
                self.assertEqual(len(result['items'][0]['metadata']['text']), 1600)
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_relocated_slide_and_ocr_require_matching_content_hash(self):
        import shutil
        from ai_material_gateway import build
        from material_store import list_materials
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);old=base/'old';new=base/'new';image=old/'out'/'scene'/'ppt'/'run'/'page.png'
            image.parent.mkdir(parents=True);image.write_bytes(b'fixture image')
            content_hash=hashlib.sha256(image.read_bytes()).hexdigest()
            (image.parent/'index.json').write_text(json.dumps({'items':[{'id':'p','path':str(image),'contentHash':content_hash}]}),encoding='utf-8')
            catalog=old/'out'/'ppt-concepts';catalog.mkdir()
            (catalog/'catalog.json').write_text(json.dumps({'pages':{str(image):{'hash':content_hash}}}),encoding='utf-8')
            (catalog/(content_hash+'.json')).write_text(json.dumps({'text':'visual text'}),encoding='utf-8')
            new.mkdir();shutil.copytree(old/'out',new/'out')
            report=sync(new);self.assertEqual((report['slides'],report['ocr'],report['errors']),(1,1,[]))
            self.assertEqual(list_materials(new,kind='ppt_ocr')['total'],1)
            manifest=build(new,write=False);self.assertEqual({x['kind'] for x in manifest['materials']},{'ppt_slide','ppt_ocr'})
            migrated=new/'out'/'scene'/'ppt'/'run'/'page.png';migrated.write_bytes(b'changed')
            report=sync(new);self.assertGreaterEqual(len(report['errors']),2)
            self.assertEqual(build(new,write=False)['materials'],[])
            self.assertEqual(image.read_bytes(),b'fixture image')

    def test_revision_overlay_is_kept_in_database(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); timeline = root / 'out' / 'day' / 'timeline.jsonl'; timeline.parent.mkdir(parents=True)
            row = {'file': 'sample.wav', 'start': 1, 'end': 2, 'text': 'old'}
            timeline.write_text(json.dumps(row) + '\n', encoding='utf-8')
            correction = {'records': {record_key(timeline, row): {'original': 'old', 'text': 'new', 'revision': 1}}}
            (root / 'transcript-corrections.json').write_text(json.dumps(correction), encoding='utf-8')
            self.assertEqual(sync(root)['transcript'], 1)
            identity = hashlib.sha256(b'transcript_segment\0out/day/timeline.jsonl\0line:1').hexdigest()[:24]
            record = get_material(identity, root)['metadata']['record']
            self.assertEqual((record['text'], record['raw_text']), ('new', 'old'))
            self.assertEqual(json.loads(timeline.read_text())['text'], 'old')
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler(root))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                response = json.load(urlopen(f'http://127.0.0.1:{server.server_port}/v1/indexed-materials?kind=transcript_segment'))
                self.assertEqual(response['total'], 1)
                self.assertEqual(response['items'][0]['metadata']['record']['text'], 'new')
                states = json.load(urlopen(f'http://127.0.0.1:{server.server_port}/v1/modules'))
                self.assertEqual(states['items'][0]['state'], 'ready')
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_watch_performs_final_scan_after_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); stop = root / 'stop'; stop.touch()
            timeline = root / 'out' / 'day' / 'timeline.jsonl'; timeline.parent.mkdir(parents=True)
            timeline.write_text(json.dumps({'text': 'late'}) + '\n', encoding='utf-8')
            script = Path(__file__).resolve().with_name('material_bridge.py')
            result = subprocess.run([sys.executable, str(script), '--root', str(root), '--watch', '--stop-file', str(stop)],
                                    capture_output=True, text=True, encoding='utf-8', timeout=20)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)['transcript'], 1)

    def test_retries_audio_and_indexes_valid_transcript_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); record = root / 'record'; record.mkdir()
            audio = record / 'sample.wav'
            with wave.open(str(audio), 'wb') as out:
                out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000); out.writeframes(b'\0\0' * 160)
            timeline = root / 'out' / 'day' / 'timeline.jsonl'; timeline.parent.mkdir(parents=True)
            timeline.write_text(json.dumps({'text': 'one'}) + '\n{bad\n' + json.dumps({'text': 'two'}) + '\n', encoding='utf-8')
            with patch('material_bridge.register_material', side_effect=RuntimeError('unavailable')):
                failed = sync(root)
            self.assertGreaterEqual(len(failed['errors']), 2)
            self.assertTrue(audio.is_file())
            result = sync(root)
            self.assertEqual((result['audio'], result['transcript']), (1, 2))
            self.assertEqual(result['errors'][0]['line'], 2)
            material_id = hashlib.sha256(b'transcript_segment\0out/day/timeline.jsonl\0line:3').hexdigest()[:24]
            self.assertEqual(get_material(material_id, root)['metadata']['record']['text'], 'two')
            self.assertEqual(sync(root)['transcript'], 2)


if __name__ == '__main__':
    unittest.main()
