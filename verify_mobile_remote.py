"""Explicit public-network integration using only a synthetic recording."""
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from ai_material_gateway import build,handler
from audio_memory_mcp import Client
from mobile_sync_remote import MobileRemote
from test_mobile_sync import package


def main():
    root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
    token='g'*40;target=root/'out/ai-gateway/access-token';target.parent.mkdir(parents=True,exist_ok=True);target.write_text(token)
    gateway=ThreadingHTTPServer(('127.0.0.1',0),handler(root,build(root),token));thread=threading.Thread(target=gateway.serve_forever,daemon=True);thread.start()
    remote=MobileRemote(root,gateway.server_port);report={}
    try:
        before=time.monotonic();info=remote.start();report['startupSeconds']=round(time.monotonic()-before,2);report['origin']=info['origin']
        def request(route,body=None,auth=True):
            req=urllib.request.Request(info['origin']+route,data=body,headers={'Authorization':'Bearer '+remote.transport.token} if auth else {})
            with urllib.request.urlopen(req,timeout=25) as response:return json.load(response)
        for attempt in range(5):
            try:assert request('/v1/sync/health')['status']=='ready';break
            except (OSError,AssertionError):
                if attempt==4:raise
                time.sleep(2)
        report['publicHttpsHealth']=True
        for route,body,auth,status in [('/v1/sync/health',None,False,401),('/v1/materials',None,True,404),('/v1/sync/remote',b'',True,404)]:
            try:request(route,body,auth);raise AssertionError('unexpected route access')
            except urllib.error.HTTPError as error:assert error.code==status
        report['restrictedRoutes']=True
        payload=package(text='公网远程录音同步验收')
        first=request('/v1/sync/recordings',payload);again=request('/v1/sync/recordings',payload)
        assert first['status']=='saved' and again['duplicate'] and first['gatewayRefreshed']
        client=Client(root,gateway.server_port);items=client.call('find_recording_materials',{'q':'公网远程录音同步验收'})
        assert items['total']==1
        content=client.call('read_recording_material',{'id':items['items'][0]['id']});assert content['content']['text']=='公网远程录音同步验收'
        audio=client.call('find_recording_materials',{'kind':'audio'});record=client.call('read_recording_material',{'id':audio['items'][0]['id']})
        assert hashlib.sha256(Path(record['localAudioPath']).read_bytes()).hexdigest()==record['sourceHash']
        report.update(uploadSaved=True,retryIdempotent=True,aiReadBack=True)
    finally:
        remote.shutdown();gateway.shutdown();gateway.server_close();thread.join(timeout=3)
        report['stopped']=remote.transport is None;report['passed']=all(report.get(k) for k in ['publicHttpsHealth','restrictedRoutes','uploadSaved','retryIdempotent','aiReadBack','stopped'])
        (root/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
