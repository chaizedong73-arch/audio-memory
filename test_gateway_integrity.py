import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ai_material_gateway import build, handler


class IntegrityTests(unittest.TestCase):
    def test_local_token_required_for_reads_and_writes(self):
        with tempfile.TemporaryDirectory() as d:
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler(Path(d), token='test-token'))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                with self.assertRaises(HTTPError) as missing:
                    urlopen(base + '/v1/health')
                self.assertEqual(missing.exception.code, 401)
                req = Request(base + '/v1/health', headers={'Authorization': 'Bearer test-token'})
                self.assertTrue(json.load(urlopen(req))['ok'])
                req = Request(base + '/v1/refresh', data=b'{}', headers={'Content-Type': 'application/json'})
                with self.assertRaises(HTTPError) as missing_write:
                    urlopen(req)
                self.assertEqual(missing_write.exception.code, 401)
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_append_corrupt_line_and_unknown_timezone(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); timeline = root / 'out' / '20261030' / 'timeline.jsonl'
            timeline.parent.mkdir(parents=True)
            row = {'file': '20261030_100000_0001.wav', 'start': 1, 'end': 2, 'text': 'first'}
            timeline.write_text(json.dumps(row) + '\n', encoding='utf-8')
            first = build(root, False)['materials'][0]
            with timeline.open('a', encoding='utf-8') as out:
                out.write('{bad\n' + json.dumps({**row, 'text': 'later'}) + '\n')
            result = build(root, False)
            self.assertEqual(len(result['materials']), 2)
            self.assertEqual(next(x for x in result['materials'] if x['preview'] == 'first')['id'], first['id'])
            self.assertIsNone(first['observedAt'])
            self.assertEqual(result['warnings'][0]['line'], 2)

    def test_full_ocr_and_snapshot_pagination(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); image = root / 'out' / 'page.png'; image.parent.mkdir()
            image.write_bytes(b'test')
            catalog = root / 'out' / 'ppt-concepts'; catalog.mkdir()
            (catalog / 'catalog.json').write_text(json.dumps({'pages': {str(image): {'hash': 'abc'}}}), encoding='utf-8')
            (catalog / 'abc.json').write_text(json.dumps({'text': 'x' * 1600}), encoding='utf-8')
            timeline = root / 'out' / 'timeline.jsonl'
            timeline.write_text(''.join(json.dumps({'text': str(i)}) + '\n' for i in range(1005)), encoding='utf-8')
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler(root))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                a = json.load(urlopen(base + '/v1/materials?kind=transcript_segment&limit=1000'))
                self.assertEqual(a['total'], 1005); self.assertEqual(a['nextOffset'], 1000)
                b = json.load(urlopen(base + '/v1/materials?kind=transcript_segment&offset=1000&snapshot=' + a['snapshot']))
                self.assertEqual(len(b['items']), 5)
                ocr = json.load(urlopen(base + '/v1/materials?kind=ppt_ocr'))['items'][0]
                self.assertEqual(len(json.load(urlopen(base + '/v1/materials/' + ocr['id'] + '/content'))['text']), 1600)
                urlopen(Request(base + '/v1/refresh', data=b'{}', headers={'Content-Type': 'application/json'})).read()
                with self.assertRaises(HTTPError) as stale:
                    urlopen(base + '/v1/materials?snapshot=' + a['snapshot'])
                self.assertEqual(stale.exception.code, 409)
            finally:
                server.shutdown(); server.server_close(); thread.join()


    def test_context_endpoint_returns_current_candidate_and_requires_token(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); folder=root/'out'/'context-auto'; folder.mkdir(parents=True)
            (folder/'state.json').write_text(json.dumps({'status':'ready'}),encoding='utf-8')
            (folder/'candidate.json').write_text(json.dumps({'candidate':{'sixElements':{'time':{'value':'早上'}},'narrative':'测试情节'},'sources':[{'id':'line:1'}]},ensure_ascii=False),encoding='utf-8')
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(root,token='test-token'))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            url=f'http://127.0.0.1:{server.server_port}/v1/context/current'
            try:
                with self.assertRaises(HTTPError) as missing: urlopen(url)
                self.assertEqual(missing.exception.code,401)
                payload=json.load(urlopen(Request(url,headers={'Authorization':'Bearer test-token'})))
                self.assertEqual(payload['state']['status'],'ready')
                self.assertEqual(payload['candidate']['candidate']['narrative'],'测试情节')
                self.assertEqual(payload['candidate']['sources'][0]['id'],'line:1')
            finally:
                server.shutdown();server.server_close();thread.join()


    def test_manual_correction_endpoint_preserves_raw_and_rejects_stale_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source=root/'out'/'20261031'/'timeline.jsonl';source.parent.mkdir(parents=True)
            original={'file':'fixture.wav','start':0,'end':1,'text':'这是试图','t':'10:00:00'}
            source.write_text(json.dumps(original,ensure_ascii=False)+'\n',encoding='utf-8');raw=source.read_bytes()
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(root,token='test-token'))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
            headers={'Authorization':'Bearer test-token','Content-Type':'application/json'}
            try:
                page=json.load(urlopen(Request(base+'/v1/materials?kind=transcript_segment',headers=headers)))
                item=page['items'][0];body=json.dumps({'id':item['id'],'snapshot':page['snapshot'],'contentVersion':item['contentVersion'],'text':'这是视图'},ensure_ascii=False).encode('utf-8')
                with self.assertRaises(HTTPError) as unauthorized:urlopen(Request(base+'/v1/transcripts/correct',data=body,headers={'Content-Type':'application/json'}))
                self.assertEqual(unauthorized.exception.code,401)
                result=json.load(urlopen(Request(base+'/v1/transcripts/correct',data=body,headers=headers)))
                self.assertTrue(result['changed']);self.assertEqual(result['revision'],1);self.assertEqual(source.read_bytes(),raw)
                corrected=json.loads(source.with_name('timeline.corrected.jsonl').read_text(encoding='utf-8'))
                self.assertEqual(corrected['text'],'这是视图')
                updated=json.load(urlopen(Request(base+'/v1/materials?kind=transcript_segment',headers=headers)))
                self.assertEqual(updated['items'][0]['data']['effectiveRecord']['text'],'这是视图')
                with self.assertRaises(HTTPError) as stale:urlopen(Request(base+'/v1/transcripts/correct',data=body,headers=headers))
                self.assertEqual(stale.exception.code,409)
            finally:server.shutdown();server.server_close();thread.join()


    def test_manual_correction_rejects_concurrent_overlay_change(self):
        from transcript_corrections import apply_manual_text,load,effective
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'out'/'day'/'timeline.jsonl';source.parent.mkdir(parents=True)
            row={'file':'fixture.wav','start':0,'end':1,'text':'原文'}
            source.write_text(json.dumps(row,ensure_ascii=False)+'\n',encoding='utf-8')
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(root,token='test-token'));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}';headers={'Authorization':'Bearer test-token','Content-Type':'application/json'}
            try:
                page=json.load(urlopen(Request(base+'/v1/materials?kind=transcript_segment',headers=headers)));item=page['items'][0]
                apply_manual_text(root,source,1,item['contentVersion'],'别人刚刚修订')
                body=json.dumps({'id':item['id'],'snapshot':page['snapshot'],'contentVersion':item['contentVersion'],'text':'过期草稿'},ensure_ascii=False).encode('utf-8')
                with self.assertRaises(HTTPError) as stale:urlopen(Request(base+'/v1/transcripts/correct',data=body,headers=headers))
                self.assertEqual(stale.exception.code,409);self.assertEqual(effective(row,source,load(root))['text'],'别人刚刚修订')
            finally:server.shutdown();server.server_close();thread.join()


    def test_visual_tasks_are_visible_through_authenticated_gateway(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'out'/'visual-tasks';folder.mkdir(parents=True)
            (folder/'task.json').write_text(json.dumps({'source':'record/camera/a.mp4','stage':'completed','pages':3,'warning':'ocr_empty_pages:1'},ensure_ascii=False),encoding='utf-8')
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(root,token='test-token'));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url=f'http://127.0.0.1:{server.server_port}/v1/visual/tasks'
            try:
                with self.assertRaises(HTTPError) as missing:urlopen(url)
                self.assertEqual(missing.exception.code,401)
                result=json.load(urlopen(Request(url,headers={'Authorization':'Bearer test-token'})))
                self.assertEqual(result['schema'],'visual-tasks/v1');self.assertEqual(result['items'][0]['pages'],3)
            finally:server.shutdown();server.server_close();thread.join()


if __name__ == '__main__':
    unittest.main()
