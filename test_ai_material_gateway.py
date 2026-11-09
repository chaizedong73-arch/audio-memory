import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from ai_material_gateway import build, filtered, handler
from transcript_corrections import record_key


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        timeline = self.root / 'out' / '20261030' / 'timeline.jsonl'
        timeline.parent.mkdir(parents=True)
        timeline.write_text(json.dumps({'file': '20261030_100000_0001.wav', 'start': 2, 'end': 4, 't': '00:00:02', 'text': '这是测试字幕'}) + '\n', encoding='utf-8')
        slide = self.root / 'out' / 'scene' / 'ppt' / 'demo' / '0001.png'
        slide.parent.mkdir(parents=True); slide.write_bytes(b'png')
        (slide.parent / 'index.json').write_text(json.dumps({'items': [{'id': 'slide-1', 'path': str(slide), 'capturedAt': 1700000000}]}, ensure_ascii=False), encoding='utf-8')

    def tearDown(self): self.temp.cleanup()

    def test_indexed_content_requires_auth_and_reads_by_identity(self):
        from material_store import register_material
        audio = self.root / 'record' / 'example.wav'
        audio.parent.mkdir(); audio.write_bytes(b'example-audio')
        identity = 'a' * 24
        register_material(identity, 'audio', 'record/example.wav', 'hash', {}, self.root)
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.root, token='test-token'))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        url = f'http://127.0.0.1:{server.server_port}/v1/indexed-materials/{identity}/content'
        try:
            with self.assertRaises(HTTPError) as error: urlopen(url)
            self.assertEqual(error.exception.code, 401)
            with urlopen(Request(url, headers={'Authorization': 'Bearer test-token'})) as response:
                self.assertEqual(response.read(), b'example-audio')
            audio.unlink()
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(url, headers={'Authorization': 'Bearer test-token'}))
            self.assertEqual(error.exception.code, 404)
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_indexes_transcript_and_slide_with_provenance(self):
        manifest = build(self.root)
        kinds = {item['kind'] for item in manifest['materials']}
        self.assertEqual(manifest['schema'], 'ai-material-gateway/v1')
        self.assertIn('transcript_segment', kinds); self.assertIn('ppt_slide', kinds)
        transcript = next(item for item in manifest['materials'] if item['kind'] == 'transcript_segment')
        self.assertEqual(transcript['preview'], '这是测试字幕')
        self.assertTrue(transcript['sourceHash']); self.assertEqual(transcript['source'], 'out/20261030/timeline.jsonl')

    def test_query_filters_without_writing(self):
        manifest = build(self.root, write=False)
        result = filtered(manifest, {'q': ['测试'], 'limit': ['1']})
        self.assertEqual(len(result), 1); self.assertEqual(result[0]['kind'], 'transcript_segment')

    def test_effective_revision_and_time_window(self):
        timeline = self.root/'out'/'20261030'/'timeline.jsonl'
        row = {'file':'20261030_191500_0001', 'start':69300, 'end':69315, 'ts':1793358900, 'text':'这是试图'}
        timeline.write_text(json.dumps(row,ensure_ascii=False)+'\n',encoding='utf-8')
        key=record_key(timeline,row)
        (self.root/'transcript-corrections.json').write_text(json.dumps({'records':{key:{'original':'这是试图','text':'这是视图','revision':1}},'annotations':[]},ensure_ascii=False),encoding='utf-8')
        manifest=build(self.root,write=False)
        items=filtered(manifest,{'kind':['transcript_segment'],'after':['2026-10-30T19:00:00+08:00'],'before':['2026-10-30T20:00:00+08:00'],'q':['视图']})
        self.assertEqual(len(items),1); self.assertEqual(items[0]['preview'],'这是视图')
        self.assertEqual(items[0]['data']['effectiveRecord']['raw_text'],'这是试图')
        self.assertEqual(items[0]['observedAt'],'2026-10-30T11:15:00Z')
        self.assertEqual(len(filtered(manifest,{'q':['视界'],'variant':['视图']})),1)

    def test_http_serves_filtered_metadata_and_one_transcript_segment(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.root))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            listing = json.loads(urlopen(base + '/v1/materials?kind=transcript_segment').read())
            self.assertEqual(len(listing['items']), 1)
            item = listing['items'][0]
            segment = json.loads(urlopen(base + '/v1/materials/' + item['id'] + '/content').read())
            self.assertEqual(segment['text'], '这是测试字幕')
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_agent_feedback_and_refresh_are_isolated_from_source(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.root))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        timeline = self.root / 'out' / '20261030' / 'timeline.jsonl'
        original = timeline.read_bytes()
        def post(path, value, headers=None):
            data = json.dumps(value, ensure_ascii=False).encode('utf-8')
            return urlopen(Request(base + path, data=data, headers={'Content-Type': 'application/json', **(headers or {})}))
        try:
            record = json.load(post('/v1/feedback', {'agent': 'notes-ai', 'status': 'need_more', 'message': '需要下一页'}))
            self.assertEqual(record['feedback']['message'], '需要下一页')
            self.assertEqual(json.load(urlopen(base + '/v1/feedback'))['items'][0]['id'], record['id'])
            self.assertEqual(timeline.read_bytes(), original)
            with self.assertRaises(HTTPError) as blocked:
                post('/v1/feedback', {}, {'Origin': 'https://untrusted.example'})
            self.assertEqual(blocked.exception.code, 403)
            with self.assertRaises(HTTPError) as invalid:
                post('/v1/feedback', ['not an object'])
            self.assertEqual(invalid.exception.code, 400)
            with timeline.open('a', encoding='utf-8') as output:
                output.write(json.dumps({'file': '20261030_100000_0002.wav', 'start': 5, 'end': 6, 'text': '新字幕'}) + '\n')
            self.assertEqual(len(json.load(urlopen(base + '/v1/materials?kind=transcript_segment'))['items']), 1)
            post('/v1/refresh', {})
            self.assertEqual(len(json.load(urlopen(base + '/v1/materials?kind=transcript_segment'))['items']), 2)
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_structured_feedback_executes_and_can_be_queried(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.root))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        def post(value):
            return json.load(urlopen(Request(base + '/v1/feedback', data=json.dumps(value).encode(), headers={'Content-Type': 'application/json'})))
        try:
            found = post({'action': 'find_materials', 'params': {'kind': 'transcript_segment', 'q': '测试'}})
            self.assertEqual(found['status'], 'completed')
            self.assertEqual(found['result']['count'], 1)
            stored = json.load(urlopen(base + '/v1/feedback/' + found['id']))
            self.assertEqual(stored['result']['items'][0]['id'], found['result']['items'][0]['id'])
            check = post({'action': 'check_materials', 'params': {'kinds': ['ppt_slide', 'ppt_ocr']}})
            self.assertEqual(check['result']['availability'], {'ppt_slide': True, 'ppt_ocr': False})
            empty = post({'action': 'find_materials', 'params': {'kind': 'ppt_ocr'}})
            self.assertEqual(empty['result']['count'], 0)
            for payload in ({'action': 'delete_materials'}, {'action': 'check_materials', 'params': {'kinds': ['unknown']}},
                            {'action': 'find_materials', 'params': {'after': '2026-10-30'}}):
                with self.assertRaises(HTTPError) as invalid:
                    post(payload)
                self.assertEqual(invalid.exception.code, 400)
            self.assertEqual(len(json.load(urlopen(base + '/v1/feedback'))['items']), 3)
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
