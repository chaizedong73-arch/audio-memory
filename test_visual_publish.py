import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import Request, urlopen

import ai_material_gateway
from material_store import list_materials
from visual_worker import publish, scan


class VisualPublishTests(unittest.TestCase):
    def test_real_video_is_processed_indexed_and_visible_without_manual_refresh(self):
        import cv2
        import numpy as np
        from test_ppt_keyframes import page
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); video=root/'record'/'camera'/'fixture.mp4'; video.parent.mkdir(parents=True)
            writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),5,(960,600))
            self.assertTrue(writer.isOpened())
            for number in (1,2):
                frame=cv2.cvtColor(np.array(page(number)),cv2.COLOR_RGB2BGR)
                for _ in range(25): writer.write(frame)
            writer.release(); original=video.read_bytes()
            token=root/'out'/'ai-gateway'/'access-token'; token.parent.mkdir(parents=True); token.write_text('fixture-token',encoding='utf-8')
            server=ThreadingHTTPServer(('127.0.0.1',0),ai_material_gateway.handler(root,token='fixture-token'))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                def local(request, timeout):
                    return urlopen(Request(f'http://127.0.0.1:{server.server_port}/v1/refresh',data=request.data,headers=dict(request.header_items()),method='POST'),timeout=timeout)
                with patch('visual_worker.urlopen',side_effect=local): result=scan(root)
                self.assertEqual(result[0]['stage'],'completed'); self.assertEqual(result[0]['pages'],2)
                self.assertFalse(result[0]['indexPending']); self.assertFalse(result[0]['gatewayPending'])
                self.assertEqual(video.read_bytes(),original)
                self.assertEqual(list_materials(root,'ppt_slide')['total'],2)
                request=Request(f'http://127.0.0.1:{server.server_port}/v1/materials?kind=ppt_slide',headers={'Authorization':'Bearer fixture-token'})
                with urlopen(request,timeout=3) as response: data=json.load(response)
                self.assertEqual(data['total'],2)
            finally:
                server.shutdown();server.server_close();thread.join()

    def test_registers_and_retries_gateway_without_reprocessing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / 'out' / 'scene' / 'ppt' / 'one' / 'frame.png'
            image.parent.mkdir(parents=True); image.write_bytes(b'image fixture')
            (image.parent / 'index.json').write_text(json.dumps({'items':[{'id':'p1','path':str(image)}]}), encoding='utf-8')
            concepts = root / 'out' / 'ppt-concepts'; concepts.mkdir()
            (concepts / 'catalog.json').write_text(json.dumps({'pages':{str(image):{'hash':'abc123'}}}), encoding='utf-8')
            (concepts / 'abc123.json').write_text(json.dumps({'text':'自动登记测试'}), encoding='utf-8')
            token_file = root / 'out' / 'ai-gateway' / 'access-token'; token_file.parent.mkdir(parents=True)
            token_file.write_text('fixture-token',encoding='utf-8')
            state = {'indexPending':True,'gatewayPending':True}
            with patch('visual_worker.urlopen', side_effect=URLError('offline')):
                publish(root,state)
            self.assertFalse(state['indexPending']); self.assertTrue(state['gatewayPending'])
            self.assertEqual(list_materials(root,'ppt_slide')['total'],1)
            self.assertEqual(list_materials(root,'ppt_ocr')['total'],1)
            server = ThreadingHTTPServer(('127.0.0.1',0), ai_material_gateway.handler(root, token='fixture-token'))
            thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            try:
                def local(request, timeout):
                    return urlopen(Request(f'http://127.0.0.1:{server.server_port}/v1/refresh',data=request.data,headers=dict(request.header_items()),method='POST'),timeout=timeout)
                with patch('visual_worker.urlopen',side_effect=local), patch('material_bridge.sync',side_effect=AssertionError('must not reindex')):
                    publish(root,state)
                self.assertFalse(state['gatewayPending'])
                request=Request(f'http://127.0.0.1:{server.server_port}/v1/materials?kind=ppt_ocr',headers={'Authorization':'Bearer fixture-token'})
                with urlopen(request,timeout=3) as response: data=json.load(response)
                self.assertEqual(data['total'],1)
                self.assertIn('自动登记测试',data['items'][0]['preview'])
            finally:
                server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
