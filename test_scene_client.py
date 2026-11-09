import base64
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
import subprocess
import sys
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from scene_client import call,exists,owner_pid,slides_directory


class SceneClientTests(unittest.TestCase):
    def test_status_and_commands_use_private_receiver_and_confine_images(self):
        with tempfile.TemporaryDirectory() as folder,tempfile.TemporaryDirectory() as other:
            root=Path(folder);frame=root/'frame.png';frame.write_bytes(b'frame');outside=Path(other)/'private.png';outside.write_bytes(b'private')
            class Handler(BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def do_GET(self):
                    if self.headers.get('Authorization')!='Bearer test-token':self.send_error(403);return
                    value={'frame':str(frame),'wifi':{'certificateQr':str(frame),'captureQr':str(outside)}}
                    data=json.dumps(value).encode();self.send_response(200);self.end_headers();self.wfile.write(data)
                def do_POST(self):
                    if self.headers.get('Authorization')!='Bearer test-token':self.send_error(403);return
                    data=self.rfile.read(int(self.headers['Content-Length']));value=json.loads(data)
                    self.send_response(200);self.end_headers();self.wfile.write(json.dumps({'result':value['name']}).encode())
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever);thread.start()
            try:
                runtime=root/'out'/'scene'/'runtime.json';runtime.parent.mkdir(parents=True)
                runtime.write_text(json.dumps({'token':'test-token','pid':123,'port':server.server_port}),encoding='utf-8')
                self.assertFalse(exists(root))
                with patch.dict('os.environ',{'AUDIO_MEMORY_TEST_SCENE_PORT':str(server.server_port)}):
                    self.assertTrue(exists(root));self.assertEqual(owner_pid(root),123)
                    status=call(root,'/status');self.assertEqual(base64.b64decode(status['frameImageBase64']),b'frame')
                    self.assertEqual(status['wifi']['captureQrImage'],'');self.assertNotIn('token',status)
                    script=Path(__file__).with_name('workbench_control.py')
                    result=subprocess.run([sys.executable,str(script),'--root',str(root),'--action','camera-call'],input=json.dumps({'path':'/status','body':None}),text=True,encoding='utf-8',capture_output=True,check=True)
                    self.assertEqual(base64.b64decode(json.loads(result.stdout)['frameImageBase64']),b'frame')
                    self.assertEqual(call(root,'/command',{'name':'snapshot'})['result'],'snapshot')
                    self.assertTrue(Path(slides_directory(root)).is_dir())
                    with self.assertRaises(ValueError):call(root,'/private')
            finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
