import io,json,os,subprocess,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from PIL import Image
from classroom_mode import set_enabled
from scene_capture import Capture,handler
from scene_remote import RemoteTransport

class RemoteTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);set_enabled(self.root,True)
  self.capture=Capture(self.root);self.capture.region_mode='full'
  self.hosts=set();self.origins=set();self.token='remote-token'
  self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.capture,hosts=self.hosts,origins=self.origins,remote=True,phone_only=True,auth_token=self.token))
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.hosts.add('test.trycloudflare.com');self.origins.add('https://test.trycloudflare.com')
 def tearDown(self):
  self.server.shutdown();self.server.server_close();self.thread.join();self.capture.locator.close();self.capture.ocr_queue.put(None);self.tmp.cleanup()
 def call(self,path,body=None,token='remote-token',origin='https://test.trycloudflare.com',host='test.trycloudflare.com'):
  headers={'Host':host,'Authorization':'Bearer '+token}
  if origin:headers['Origin']=origin
  request=urllib.request.Request(f'http://127.0.0.1:{self.server.server_port}'+path,data=body,headers=headers)
  with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=4) as response:return response.read()
 def test_dynamic_origin_page_frame_and_minimal_status(self):
  self.assertIn(b'getUserMedia',self.call('/'))
  self.call('/hello',b'{"device":"fixture"}')
  image=io.BytesIO();Image.new('RGB',(320,180),'#123456').save(image,'PNG');self.call('/frame',image.getvalue())
  self.assertEqual((self.capture.folder/'preview.png').read_bytes(),image.getvalue())
  owner=self.capture.owner;state=json.loads(self.call('/phone'));self.assertEqual(self.capture.owner,owner)
  self.assertNotIn('wifi',state);self.assertNotIn('frame',state);self.assertNotIn('remote',state)
  self.assertTrue(state['connected']);self.assertEqual(self.capture.phone,'fixture')
 def test_reject_missing_token_wrong_origin_host_and_local_token(self):
  for kwargs in ({'token':''},{'origin':'https://evil.invalid'},{'host':'evil.invalid'},{'token':self.capture.token}):
   with self.subTest(kwargs=kwargs):
    with self.assertRaises(urllib.error.HTTPError) as error:self.call('/phone',**kwargs)
    self.assertEqual(error.exception.code,403)
 def test_no_desktop_controls_or_local_files_exposed(self):
  for path,body in [('/status',None),('/wifi',b'{}'),('/remote',b'{}'),('/remote/stop',b'{}'),('/analyze',b'{}'),('/out/scene/runtime.json',None)]:
   with self.subTest(path=path):
    with self.assertRaises(urllib.error.HTTPError) as error:self.call(path,body)
    self.assertEqual(error.exception.code,404)
  with self.assertRaises(urllib.error.HTTPError):self.call('/command',b'{"name":"snapshot"}')
  self.call('/command',b'{"name":"disconnect"}');self.assertTrue(self.capture.closing)
 def test_oversized_or_invalid_frames_do_not_replace_existing(self):
  image=io.BytesIO();Image.new('RGB',(32,32)).save(image,'PNG');self.call('/frame',image.getvalue())
  with self.assertRaises(urllib.error.HTTPError):self.call('/frame',b'invalid')
  self.assertEqual((self.capture.folder/'preview.png').read_bytes(),image.getvalue())
 def test_tunnel_lifecycle_registers_and_revokes_qr(self):
  transport=RemoteTransport(self.capture)
  fake=unittest.mock.Mock();fake.stdout=io.BytesIO(b'https://test.trycloudflare.com\nRegistered tunnel connection\n');fake.poll.return_value=None
  # Keep the fake output stream open after registration, like a running tunnel.
  def read():
   transport.hosts.add('test.trycloudflare.com');transport.origins.add('https://test.trycloudflare.com')
   transport.info['origin']='https://test.trycloudflare.com';transport.ready.set()
  with patch.object(transport,'registry') as registry,patch.object(transport,'read_output',side_effect=read),patch('scene_remote.subprocess.Popen',return_value=fake),patch.dict(os.environ,{'AUDIO_MEMORY_REGISTRY_PATH':'fixture','AUDIO_MEMORY_REGISTRY_EXECUTABLE':'fixture'}),patch('scene_remote.Path.is_file',return_value=True):
   try:
    info=transport.start(timeout=2);self.assertEqual(info['status'],'ready');self.assertIn('/#',info['url']);self.assertTrue(Path(info['captureQr']).exists())
   finally:transport.close()
   self.assertEqual(registry.call_args_list[0].args[0],'register');self.assertEqual(registry.call_args_list[-1].args[0],'unregister')
   fake.terminate.assert_called_once();self.assertFalse((transport.folder/'capture-qr.png').exists())
 def test_tunnel_start_failure_closes_receiver(self):
  transport=RemoteTransport(self.capture)
  with patch.dict(os.environ,{'AUDIO_MEMORY_REGISTRY_PATH':'fixture','AUDIO_MEMORY_REGISTRY_EXECUTABLE':'fixture'}),patch('scene_remote.Path.is_file',return_value=True),patch('scene_remote.subprocess.Popen',side_effect=OSError('fixture spawn failure')):
   with self.assertRaises(OSError):transport.start(timeout=.1)
  self.assertTrue(transport.closed);self.assertFalse(transport.thread.is_alive())
 def test_cancel_during_connection_stops_registered_process(self):
  transport=RemoteTransport(self.capture);self.capture.closing=True
  fake=unittest.mock.Mock();fake.stdout=io.BytesIO();fake.poll.return_value=None
  with patch.object(transport,'registry') as registry,patch.object(transport,'read_output'),patch('scene_remote.subprocess.Popen',return_value=fake),patch.dict(os.environ,{'AUDIO_MEMORY_REGISTRY_PATH':'fixture','AUDIO_MEMORY_REGISTRY_EXECUTABLE':'fixture'}),patch('scene_remote.Path.is_file',return_value=True):
   with self.assertRaisesRegex(ValueError,'取消'):transport.start(timeout=10)
   fake.terminate.assert_called_once();self.assertEqual(registry.call_args_list[-1].args[0],'unregister')
  self.assertTrue(transport.closed);self.assertFalse(transport.thread.is_alive())

if __name__=='__main__':unittest.main()
