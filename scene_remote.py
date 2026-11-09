"""On-demand HTTPS phone transport; tunnel exposes only a restricted loopback receiver."""
import json, os, re, secrets, subprocess, threading, time, uuid
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
PUBLIC_URL = re.compile(r'https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com\b')

class RemoteTransport:
 def __init__(self, capture, handler_factory=None, name_prefix="Scene-Remote-", description="录音记忆远程手机采集，结束采集即关闭"):
  self.capture=capture;self.handler_factory=handler_factory;self.description=description;self.token=secrets.token_urlsafe(32);self.process=None;self.thread=None;self.reader=None
  self.server=None;self.closed=False;self.registered=False;self.name=name_prefix+uuid.uuid4().hex
  self.hosts=set();self.origins=set();self.ready=threading.Event();self.failure=False
  self.folder=capture.folder/'remote';self.folder.mkdir(exist_ok=True)
  self.info={'status':'starting','message':'正在建立远程连接…'}
 def registry(self,*args):
  registry=os.environ.get('AUDIO_MEMORY_REGISTRY_PATH');executable=os.environ.get('AUDIO_MEMORY_REGISTRY_EXECUTABLE')
  if not registry or not executable:raise ValueError('缺少进程管理配置，无法开启远程连接')
  result=subprocess.run([executable,registry,*args],capture_output=True,timeout=15,
   env={**os.environ,'ELECTRON_RUN_AS_NODE':'1'},creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  if result.returncode:raise ValueError('远程连接进程登记失败')
 def start(self, timeout=60):
  if self.handler_factory is None:
   from scene_capture import handler
  else:handler=self.handler_factory
  binary=ROOT/'tools/cloudflared/cloudflared.exe'
  if not binary.is_file():raise ValueError('缺少远程连接组件，请补齐 tools/cloudflared/cloudflared.exe')
  # Validate registry configuration before starting any background process.
  if not os.environ.get('AUDIO_MEMORY_REGISTRY_PATH') or not os.environ.get('AUDIO_MEMORY_REGISTRY_EXECUTABLE'):
   raise ValueError('缺少进程管理配置，无法开启远程连接')
  self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.capture,hosts=self.hosts,origins=self.origins,remote=True,phone_only=True,auth_token=self.token))
  self.server.daemon_threads=True
  self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.2},daemon=True);self.thread.start()
  try:
   self.process=subprocess.Popen([str(binary),'tunnel','--no-autoupdate','--protocol','http2','--url',f'http://127.0.0.1:{self.server.server_port}'],
    cwd=str(self.folder),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   self.registry('register','--owner','GPT','--name',self.name,'--pid',str(self.process.pid),'--desc',self.description)
   self.registered=True
   self.reader=threading.Thread(target=self.read_output,daemon=True);self.reader.start()
   deadline=time.monotonic()+timeout
   while not self.ready.wait(.2) and time.monotonic()<deadline:
    if self.capture.closing:raise ValueError('采集已结束，取消远程连接')
   if not self.ready.is_set() or self.failure or self.process.poll() is not None:
    raise ValueError('远程连接未能建立，校园网可能阻止中转服务；请查看远程连接日志')
   origin=self.info['origin']
   qr=self.folder/'capture-qr.png'
   if self.handler_factory is None:
    import qrcode
    qrcode.make(origin+'/#'+self.token).save(qr)
   self.info={'status':'ready','origin':origin,'url':origin+'/#'+self.token,'captureQr':str(qr) if self.handler_factory is None else None,'provider':'cloudflare-quick-tunnel',
    'message':'手机可使用流量扫码；无需同一 Wi-Fi 或安装证书。'}
   return self.info
  except Exception:
   self.close();raise
 def read_output(self):
  try:
   with (self.folder/'tunnel.log').open('ab') as log:
    for raw in iter(self.process.stdout.readline,b''):
     log.write(raw);log.flush()
     line=raw.decode('utf-8',errors='replace');match=PUBLIC_URL.search(line)
     if match:
      origin=match.group(0);self.hosts.add(urlparse(origin).netloc);self.origins.add(origin);self.info['origin']=origin
     if 'Registered tunnel connection' in line and self.info.get('origin'):self.ready.set()
  finally:
   self.failure=True;self.ready.set()
   if not self.closed:self.info={'status':'error','message':'远程连接已断开，请重新配对'}
 def close(self):
  if self.closed:return
  self.closed=True
  if self.process:
   if self.process.poll() is None:
    self.process.terminate()
    try:self.process.wait(timeout=5)
    except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
   if self.reader:self.reader.join(timeout=3)
   if self.process.stdout:self.process.stdout.close()
  try:
   if self.registered:
    self.registry('unregister','--name',self.name);self.registered=False
  finally:
   if self.server:
    self.server.shutdown();self.server.server_close()
   if self.thread:self.thread.join(timeout=3)
   (self.folder/'capture-qr.png').unlink(missing_ok=True)
   self.info={'status':'stopped'}
