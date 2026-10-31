import io,json,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from PIL import Image
from classroom_mode import set_enabled
from scene_capture import Capture,handler,PORT

class SceneTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);set_enabled(self.root,True);self.c=Capture(self.root)
 def tearDown(self):self.tmp.cleanup()
 def image(self):
  buf=io.BytesIO();Image.new('RGB',(320,180),'#234567').save(buf,'PNG');return buf.getvalue()
 def test_snapshot_provenance_and_locality(self):
  self.c.image(self.image());file=Path(self.c.command('snapshot'))
  self.assertTrue(file.is_relative_to(self.root));self.assertEqual(file.read_bytes(),self.image())
  self.assertIn('snapshot',(self.c.folder/'events.jsonl').read_text())
 def begin(self):
  import time
  self.c.last_phone=time.time();self.c.command('record');return self.c.begin('video/webm;codecs=vp8')
 def test_order_retry_finalize(self):
  sid=self.begin();self.c.chunk(sid,0,b'header');self.c.chunk(sid,0,b'header')
  with self.assertRaises(ValueError):self.c.chunk(sid,2,b'bad')
  self.c.chunk(sid,1,b'body');self.c.finish(sid)
  self.assertEqual(self.c.record_path.read_bytes(),b'headerbody');self.assertEqual(self.c.receipt['state'],'saved')
  self.assertNotIn('.partial',self.c.record_path.name)
 def test_disconnect_retains_partial(self):
  sid=self.begin();self.c.chunk(sid,0,b'header');self.c.finish(sid,False)
  self.assertEqual(self.c.receipt['state'],'incomplete');self.assertTrue(self.c.record_path.exists())
 def test_mode_and_file_validation(self):
  set_enabled(self.root,False)
  with self.assertRaises(ValueError):self.c.command('record')
  with self.assertRaises((ValueError,OSError)):self.c.image(b'not png')
  with self.assertRaises(ValueError):self.c.analyze('other')
 def test_low_disk_protects_existing(self):
  sid=self.begin()
  with patch('scene_capture.shutil.disk_usage') as disk:
   disk.return_value.free=10
   with self.assertRaises(ValueError):self.c.chunk(sid,0,b'x')
  self.assertEqual(self.c.record_path.stat().st_size,0)
 def test_analysis_is_manual_and_retains_source(self):
  import time
  self.c.image(self.image())
  with patch('visual_vocabulary_test.run') as model:
   model.return_value={'text':'测试文字','usage':{},'elapsedSeconds':0}
   self.assertFalse(self.c.analysis_busy);model.assert_not_called()
   self.c.analyze('local:ppocr-v6-small')
   deadline=time.monotonic()+3
   while self.c.analysis_busy and time.monotonic()<deadline:time.sleep(.01)
   self.assertEqual(self.c.analysis['status'],'done');job=model.call_args.args[0]
   self.assertTrue(Path(job['image']).is_relative_to(self.root));self.assertTrue(Path(job['_runDir'],'image.result.json').exists())
   self.assertEqual(job['model'],'local:ppocr-v6-small')
 def test_http_auth_origin_upload(self):
  server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.c));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  url='http://127.0.0.1:'+str(server.server_port)
  def call(path,body=None,token=True,origin=None):
   headers={'Host':f'localhost:{PORT}'}
   if token:headers['Authorization']='Bearer '+self.c.token
   if origin:headers['Origin']=origin
   req=urllib.request.Request(url+path,data=body,headers=headers)
   with urllib.request.urlopen(req,timeout=3) as response:return response.read()
  try:
   self.assertIn(b'getUserMedia',call('/'))
   with self.assertRaises(urllib.error.HTTPError):call('/status',token=False)
   with self.assertRaises(urllib.error.HTTPError):call('/status',origin='https://evil.invalid')
   call('/frame',self.image());self.assertTrue(json.loads(call('/status'))['frame'])
   self.assertEqual(json.loads(call('/command',b'{"name":"snapshot"}'))['ok'],True)
  finally:server.shutdown();server.server_close();thread.join()

class UsbTests(unittest.TestCase):
 def test_unauthorized_device_does_not_open_or_replace_server(self):
  import scene_usb
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'tools/android/platform-tools').mkdir(parents=True);(root/'tools/android/platform-tools/adb.exe').touch()
   c=Capture(root);c.save()
   with patch('scene_usb.socket.create_connection'),patch('scene_usb.subprocess.run') as run,patch('scene_usb.subprocess.Popen') as spawn:
    run.return_value.returncode=0;run.return_value.stdout='List of devices attached\nphone unauthorized\n';run.return_value.stderr=''
    with self.assertRaisesRegex(ValueError,'USB调试'):scene_usb.connect(root)
    spawn.assert_not_called();self.assertEqual(run.call_count,1)
 def test_shared_server_cleanup_never_kills_server(self):
  import scene_usb
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'tools/android/platform-tools').mkdir(parents=True);(root/'tools/android/platform-tools/adb.exe').touch()
   c=Capture(root);c.save();data=json.loads((c.folder/'runtime.json').read_text());data.update(adbPort=5037,adbOwned=False,usbSerial='phone')
   (c.folder/'runtime.json').write_text(json.dumps(data))
   with patch('scene_usb.subprocess.run') as run,patch('scene_usb.socket.create_connection'):
    scene_usb.cleanup(root);self.assertEqual(run.call_count,1);self.assertNotIn('kill-server',run.call_args.args[0])

if __name__=='__main__':unittest.main()
