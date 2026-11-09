"""Reuse the existing on-demand tunnel, with an upload-only recording receiver."""
import base64
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from scene_remote import RemoteTransport


class MobileRemote:
    def __init__(self, root, gateway_port=8768):
        self.root=Path(root);self.gateway_port=gateway_port;self.lock=threading.Lock();self.transport=None
        folder=self.root/'out/mobile-sync-tunnel';folder.mkdir(parents=True,exist_ok=True)
        self.capture=SimpleNamespace(folder=folder,closing=False)
    def status(self):
        transport=self.transport
        if not transport:return {'status':'stopped'}
        if transport.info.get('status')!='ready':return {'status':transport.info.get('status','error'),'message':'远程连接不可用，请重新开启并配对。'}
        value={'url':transport.info['origin'],'token':transport.token,'transport':'remote'}
        code='am1.'+base64.urlsafe_b64encode(json.dumps(value,separators=(',',':')).encode()).decode().rstrip('=')
        return {'status':'ready','code':code,'origin':transport.info['origin'],'provider':'cloudflare-quick-tunnel',
                'message':'手机可用移动数据同步；资料经Cloudflare中转，关闭或重开通道后须重新配对。'}
    def start(self):
        from mobile_sync import make_handler
        with self.lock:
            if self.capture.closing:raise RuntimeError('receiver is closing')
            if self.transport and self.transport.info.get('status')=='ready':return self.status()
            if self.transport:self.transport.close()
            factory=lambda capture,hosts=None,auth_token=None,**kwargs:make_handler(self.root,auth_token,self.gateway_port,hosts=hosts)
            transport=RemoteTransport(self.capture,handler_factory=factory,name_prefix='Mobile-Sync-Remote-',description='录音记忆远程录音同步；关闭接收即终止')
            self.transport=transport
            try:
                transport.start()
                # The camera transport's QR is not used by the native recording app.
                return self.status()
            except Exception:
                transport.close();self.transport=None;raise
    def stop(self):
        with self.lock:
            if self.transport:self.transport.close();self.transport=None
            return {'status':'stopped'}
    def shutdown(self):
        self.capture.closing=True
        self.stop()
