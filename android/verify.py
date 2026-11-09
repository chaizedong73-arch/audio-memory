"""Run the test APK only in our isolated emulator and verify actual PC materials."""
import hashlib
import json
from pathlib import Path
import secrets
import shlex
import ssl
import subprocess
import sys
import threading
import time
import argparse
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from ai_material_gateway import build, handler
from audio_memory_mcp import Client
from mobile_sync import make_handler, certificate
from mobile_sync_remote import MobileRemote


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--remote',action='store_true');parser.add_argument('--apk',type=Path,default=ROOT/'android/dist/AudioMemory-Android-Test.apk');options=parser.parse_args()
    adb=Path.home()/'.cache/xianqi-build/android-sdk/platform-tools/adb.exe'
    out=ROOT/('test-artifacts/2026-11-06-mobile-remote/android' if options.remote else 'test-artifacts/2026-11-06-mobile');out.mkdir(parents=True,exist_ok=True)
    fixture=out/('pc-fixture-'+str(int(time.time())));fixture.mkdir(parents=True)
    def command(*args,**kw):return subprocess.run([str(adb),'-P','5041','-s','emulator-5580',*map(str,args)],check=True,**kw)
    # This serial belongs to the fresh AudioMemoryTest AVD, never a USB phone.
    if 'device' not in command('get-state',capture_output=True,text=True).stdout:raise RuntimeError('test emulator unavailable')
    deadline=time.monotonic()+90
    while command('shell','getprop','sys.boot_completed',capture_output=True,text=True).stdout.strip()!='1':
        if time.monotonic()>deadline:raise RuntimeError('test emulator boot timed out')
        time.sleep(1)
    token=secrets.token_urlsafe(32);token_path=fixture/'out/ai-gateway/access-token';token_path.parent.mkdir(parents=True);token_path.write_text(token)
    gateway=ThreadingHTTPServer(('127.0.0.1',0),handler(fixture,build(fixture),token));gateway.daemon_threads=True
    sync_token=secrets.token_urlsafe(32);cert,key,pin=certificate(fixture)
    base=make_handler(fixture,sync_token,gateway.server_port)
    class FixtureHandler(base):
        def do_POST(self):
            if self.path in ('/chat/completions','/fail/chat/completions','/audio/transcriptions'):
                if not self.authorized():self.reply(401,{'error':'unauthorized'});return
                length=int(self.headers.get('Content-Length','0'));body=self.rfile.read(length)
                if self.path=='/fail/chat/completions':self.reply(503,{'error':'fixture failure'});return
                if self.path=='/audio/transcriptions':
                    assert b'name="file"' in body and b'fixture-model' in body
                    self.reply(200,{'text':'兼容语音转写接口验收'});return
                request=json.loads(body);assert request['model']=='fixture-model' and request['messages'][0]['content'][0]['type']=='input_audio'
                self.reply(200,{'choices':[{'message':{'content':'原生云端请求协议验收'}}],'usage':{'prompt_tokens':107,'completion_tokens':12}});return
            super().do_POST()
    receiver=ThreadingHTTPServer(('127.0.0.1',0),FixtureHandler);receiver.daemon_threads=True
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(str(cert),str(key));receiver.socket=tls.wrap_socket(receiver.socket,server_side=True)
    threads=[]
    for server in (gateway,receiver):
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start();threads.append(t)
    remote=None
    try:
        remote_arg=''
        if options.remote:
            remote=MobileRemote(fixture,gateway.server_port);remote_info=remote.start();remote_arg=' -e remotePairing '+shlex.quote(remote_info['code'])
        command('install','-r',options.apk.resolve(),capture_output=True)
        command('shell','pm','clear','org.audiomemory.mobile',capture_output=True)
        command('shell','pm','grant','org.audiomemory.mobile','android.permission.RECORD_AUDIO')
        pairing=json.dumps({'url':f'https://10.0.2.2:{receiver.server_port}','token':sync_token,'fingerprint':pin},separators=(',',':'))
        shell='am instrument -w -e pairing '+shlex.quote(pairing)+remote_arg+' org.audiomemory.mobile/.MobileChecks'
        result=command('shell',shell,capture_output=True,text=True,encoding='utf-8',timeout=150)
        (out/'instrumentation.txt').write_text(result.stdout+result.stderr,encoding='utf-8')
        if 'PASS native recording' not in result.stdout:raise AssertionError(result.stdout)
        for name in ['01-empty','02-录音','02-资料','02-同步','02-设置']:
            raw=command('exec-out','run-as','org.audiomemory.mobile','cat','files/'+name+'.png',capture_output=True).stdout
            assert raw.startswith(b'\x89PNG'),raw[:100]
            (out/(name+'.png')).write_bytes(raw)
        client=Client(fixture,gateway.server_port)
        rows=client.call('find_recording_materials',{'q':'安卓同步验收','limit':10})
        assert rows['total']==1,rows
        transcript=client.call('read_recording_material',{'id':rows['items'][0]['id']})
        assert transcript['content']['text']=='安卓同步验收：修订后仍然可以追溯音频'
        audio=client.call('find_recording_materials',{'kind':'audio'})
        identities=[x['data']['mobileId'] for x in audio['items']];assert len(identities)==len(set(identities)),audio
        source=next(x for x in audio['items'] if x['data']['mobileId']==transcript['content']['mobileId'])
        material=client.call('read_recording_material',{'id':source['id']})
        local=Path(material['localAudioPath']);assert local.is_file()
        assert hashlib.sha256(local.read_bytes()).hexdigest()==material['data']['sha256']
        # Validate the actual newline-delimited stdio entry point, including tool invocation.
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18'}},
                  {'jsonrpc':'2.0','method':'notifications/initialized'},
                  {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'find_recording_materials','arguments':{'q':'安卓同步验收'}}}]
        stdio=subprocess.run([sys.executable,str(ROOT/'audio_memory_mcp.py'),'--root',str(fixture),'--port',str(gateway.server_port)],input=''.join(json.dumps(m,ensure_ascii=False)+'\n' for m in messages),capture_output=True,text=True,encoding='utf-8',timeout=25,check=True)
        replies=[json.loads(line) for line in stdio.stdout.splitlines()];assert len(replies)==2 and not replies[-1]['result']['isError']
        evidence={'fixture':str(fixture),'mcp':replies,'transcript':transcript,'audio':material,'apk':'test build only','network':'public Cloudflare HTTPS from emulator' if options.remote else 'emulator host alias 10.0.2.2; not physical Wi-Fi'}
        (out/'chain-result.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
        print('PASS emulator → pinned HTTPS sync → durable PC files → loopback material gateway → actual stdio MCP')
    finally:
        if remote:remote.shutdown()
        for server in (receiver,gateway):server.shutdown();server.server_close()
        for t in threads:t.join(timeout=3)


if __name__=='__main__':main()
