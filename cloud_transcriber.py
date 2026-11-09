"""Transcribe newly recorded audio using the configured Ark audio model."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import time
import urllib.request
from urllib.parse import urlparse
from cloud_usage import record_usage, UsageRecordingError
from material_exchange import MaterialExchange
import wave, uuid

from cloud_asr_trial import MODEL, payload

def transcribe(file, root, config_path, send=None):
    root=Path(root);file=Path(file)
    with wave.open(str(file),'rb') as audio:
        frames=audio.readframes(audio.getnframes())
        if frames and not any(frames):
            return {'file':file.stem,'text':'','model':MODEL,'reason':'digital_silence'}
    duration,body=payload(file)
    protocol=os.environ.get('AUDIO_MEMORY_ASR_PROTOCOL','ark_audio')
    model=os.environ.get('AUDIO_MEMORY_ASR_MODEL',MODEL)
    if protocol=='ark_audio' and model.lower()=='doubao-seed-2.0-mini':model=MODEL
    body['model']=model
    official=False
    if send is None:
        if os.environ.get('AUDIO_MEMORY_ASR_URL'):
            base=os.environ['AUDIO_MEMORY_ASR_URL'].rstrip('/');key=os.environ.get('AUDIO_MEMORY_ASR_KEY','')
            for suffix in ('/chat/completions','/audio/transcriptions'):
                if base.endswith(suffix):base=base[:-len(suffix)]
        else:
            config=json.loads(Path(config_path).read_text(encoding='utf-8-sig'));base=config['ark_base_url'].rstrip('/');key=config['ark_api_key']
        if protocol=='openai_transcription':
            boundary='audio-memory-'+uuid.uuid4().hex
            content=(f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{model}\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode()+file.read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
            req=urllib.request.Request(base+'/audio/transcriptions',data=content,headers={'Authorization':'Bearer '+key,'Content-Type':'multipart/form-data; boundary='+boundary})
        elif protocol=='ark_audio':
            req=urllib.request.Request(base+'/chat/completions',data=json.dumps(body).encode('utf-8'),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        else:raise ValueError('unsupported protocol')
        def send(request):
            with urllib.request.urlopen(request,timeout=60) as response:return json.load(response)
        official=urlparse(base).hostname in ('ark.cn-beijing.volces.com','ark.cn-beijing.volcengineapi.com')
        try:
            result=send(req)
        except Exception as error:
            record_usage(root,file=file,model=model,protocol=protocol,duration=duration,error=error,official=official)
            raise
    else:
        try:
            result=send(body)
        except Exception as error:
            record_usage(root,file=file,model=model,protocol=protocol,duration=duration,error=error)
            raise
    # Even empty or malformed responses may have consumed paid tokens.
    record_usage(root,file=file,model=model,protocol=protocol,duration=duration,result=result,official=official)
    if protocol=='openai_transcription':text=result.get('text','')
    else:
        choice=result['choices'][0]
        if choice.get('finish_reason')=='length':raise ValueError('response truncated')
        text=choice['message'].get('content','')
    if not isinstance(text,str):raise ValueError('invalid response')
    start=dt.datetime.strptime(file.stem[:15],'%Y%m%d_%H%M%S');offset=(start-start.replace(hour=0,minute=0,second=0,microsecond=0)).total_seconds()
    row={'start':offset,'end':offset+duration,'ts':start.timestamp(),'t':start.strftime('%H:%M:%S'),'date':start.strftime('%Y-%m-%d'),'file':file.stem,'text':text.strip(),'model':model,'timing':'whole_chunk_not_word_aligned'}
    if text.strip():
        MaterialExchange(root).append_transcripts(start.strftime('%Y%m%d'), [row], cloud=True)
    return row

def run(root,config_path,stop_file):
    root=Path(root);stop_file=Path(stop_file);cutoff=time.time();completed=set();attempts={}
    print('云端音频转写已启动；只处理本次启动后的音频。',flush=True)
    while True:
        for name in MaterialExchange(root).recordings(('.wav',)):
            file = Path(name)
            if file.stat().st_mtime<cutoff or file.name in completed or attempts.get(file.name,0)>=3:continue
            try:
                row=transcribe(file,root,config_path);completed.add(file.name)
                print(json.dumps({'file':file.name,'characters':len(row['text'])},ensure_ascii=False),flush=True)
            except UsageRecordingError:
                completed.add(file.name)
                print('费用账本写入失败：该段不自动重试，原音频已保留，请检查磁盘和日志。',flush=True)
            except Exception as error:
                attempts[file.name]=attempts.get(file.name,0)+1
                print('云端转写失败：'+type(error).__name__+'，音频已保留。',flush=True)
        if stop_file.exists():break
        for _ in range(20):
            if stop_file.exists():break
            time.sleep(.1)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--config',type=Path,required=True);p.add_argument('--stop-file',type=Path,required=True);args=p.parse_args()
    if not os.environ.get('AUDIO_MEMORY_ASR_URL') and not args.config.is_file():raise SystemExit('未配置云端 API')
    run(args.root,args.config,args.stop_file)
