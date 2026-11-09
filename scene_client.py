"""Local camera control contract; the UI never reads the receiver token."""
import base64
import json
import os
from pathlib import Path
import urllib.error
import urllib.request


def _runtime(root):
    root=Path(root).resolve();path=(root/'out'/'scene'/'runtime.json').resolve()
    if not path.is_relative_to(root): raise ValueError('采集运行位置无效')
    state=json.loads(path.read_text(encoding='utf-8-sig'))
    allowed_port=int(os.environ.get('AUDIO_MEMORY_TEST_SCENE_PORT','19643'))
    if not isinstance(state.get('token'),str) or not state['token'] or type(state.get('port')) is not int or state['port'] != allowed_port:
        raise ValueError('采集运行信息无效')
    return root,state


def exists(root):
    try: _runtime(root);return True
    except (OSError,ValueError,TypeError): return False


def owner_pid(root):
    _,state=_runtime(root);pid=state.get('pid')
    if type(pid) is not int or pid<=0:raise ValueError('采集进程无效')
    return pid


def slides_directory(root):
    root=Path(root).resolve();folder=(root/'out'/'scene'/'ppt').resolve()
    if not folder.is_relative_to(root):raise ValueError('画面目录无效')
    folder.mkdir(parents=True,exist_ok=True);return str(folder)


def call(root,path,body=None):
    if path not in ('/status','/wifi','/command','/analyze'):raise ValueError('不支持的采集操作')
    if path=='/status' and body is not None or path!='/status' and not isinstance(body,dict):raise ValueError('采集请求无效')
    root,state=_runtime(root)
    request=urllib.request.Request('http://127.0.0.1:'+str(state['port'])+path,
        data=json.dumps(body,ensure_ascii=False).encode('utf-8') if body is not None else None,
        headers={'Authorization':'Bearer '+state['token'],'Content-Type':'application/json'})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=30 if path=='/wifi' else 3) as response:
            result=json.load(response)
    except urllib.error.HTTPError as error:
        try: message=json.load(error).get('error','采集请求失败')
        except (ValueError,AttributeError): message='采集请求失败'
        raise ValueError(str(message)) from error
    if not isinstance(result,dict):raise ValueError('采集回执无效')
    if path=='/status':
        def image(value):
            if not value:return ''
            file=Path(value).resolve()
            if not file.is_relative_to(root) or not file.is_file():return ''
            with file.open('rb') as stream:data=stream.read(8*1024*1024+1)
            return base64.b64encode(data).decode('ascii') if len(data)<=8*1024*1024 else ''
        result['frameImageBase64']=image(result.get('frame'))
        wifi=result.get('wifi')
        if isinstance(wifi,dict):
            wifi['certificateQrImage']=image(wifi.get('certificateQr'))
            wifi['captureQrImage']=image(wifi.get('captureQr'))
    return result
