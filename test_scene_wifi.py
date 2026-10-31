import hashlib,json,socket,ssl,tempfile,time,unittest,urllib.request,urllib.error
from pathlib import Path
from scene_capture import Capture
from scene_wifi import WifiTransport,TLS_PORT,CERT_PORT,local_ip

class WifiTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.ip=local_ip()
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.capture=Capture(self.root)
  self.transport=WifiTransport(self.capture,self.ip);self.capture.wifi=self.transport;self.transport.start()
 def tearDown(self):self.transport.close();self.tmp.cleanup()
 def fetch(self,path,auth=True,origin=None,trusted=True):
  context=ssl.create_default_context(cafile=str(self.root/'config/scene-tls/ca.pem')) if trusted else ssl.create_default_context()
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context))
  headers={}
  if auth:headers['Authorization']='Bearer '+self.capture.token
  if origin:headers['Origin']=origin
  return opener.open(urllib.request.Request(f'https://{self.ip}:{TLS_PORT}'+path,headers=headers),timeout=5).read()
 def test_trusted_https_and_mobile_page(self):
  self.assertIn(b'getUserMedia',self.fetch('/',auth=False))
  self.assertIn(b'connected',self.fetch('/status'))
  with self.assertRaises(urllib.error.URLError):self.fetch('/',trusted=False)
 def test_reject_missing_token_and_foreign_origin(self):
  for kwargs in [{'auth':False},{'origin':'https://evil.invalid'}]:
   with self.assertRaises(urllib.error.HTTPError) as error:self.fetch('/status',**kwargs)
   self.assertEqual(error.exception.code,403)
 def test_phone_cannot_keep_desktop_alive(self):
  self.capture.owner=42;self.fetch('/status');self.assertEqual(self.capture.owner,42)
 def test_download_only_public_certificate_and_cleanup(self):
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
  certificate=opener.open(self.transport.info['certificateUrl'],timeout=3).read()
  self.assertEqual(hashlib.sha256(certificate).hexdigest().upper(),self.transport.info['fingerprint'])
  for path in ['/ca-key.pem','/pairing.json','/']:
   with self.assertRaises(urllib.error.HTTPError):opener.open(f'http://{self.ip}:{CERT_PORT}'+path,timeout=3)
  self.assertTrue(Path(self.transport.info['captureQr']).exists())
 def test_qr_url_has_secure_origin_and_fragment(self):
  self.assertTrue(self.transport.info['url'].startswith(f'https://{self.ip}:{TLS_PORT}/#'))
  self.assertNotIn('token=',self.transport.info['url'])

if __name__=='__main__':unittest.main()
