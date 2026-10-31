"""Foreground supervisor for recorder and local transcriber, with owned-process cleanup."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
import tempfile
import uuid
import threading

ROOT=Path(__file__).resolve().parent

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--device',default='auto');ap.add_argument('--model',default='base');ap.add_argument('--mode',choices=('local','cloud'),default='local');ap.add_argument('--cloud-config',type=Path);ap.add_argument('--stop-file',type=Path);ap.add_argument('--ready-file',type=Path);ap.add_argument('--root',type=Path,default=ROOT);ap.add_argument('--registry',type=Path);ap.add_argument('--registry-executable',type=Path);ap.add_argument('--parent-registered-file',type=Path);args=ap.parse_args()
    if args.mode=='cloud' and not os.environ.get('AUDIO_MEMORY_ASR_URL') and (not args.cloud_config or not args.cloud_config.is_file()):ap.error('cloud API configuration missing')
    if bool(args.registry) != bool(args.registry_executable):
        ap.error('registry and registry-executable must be supplied together')
    data_root=args.root.resolve()
    if args.parent_registered_file:
        deadline=time.monotonic()+10
        while not args.parent_registered_file.exists() and time.monotonic()<deadline:
            if args.stop_file and args.stop_file.exists(): return
            time.sleep(.05)
        if not args.parent_registered_file.exists():
            raise RuntimeError('Supervisor registration did not complete')
    def start_module(name, script, arguments):
        command=[sys.executable,str(ROOT/script),*arguments]
        env=None
        if args.registry:
            command=[str(args.registry_executable),str(args.registry),'run','--owner','GPT','--name',f'Audio-Memory-{name}-{uuid.uuid4()}',
                     '--desc',f'录音记忆 {name}','--',*command]
            env={**os.environ,'ELECTRON_RUN_AS_NODE':'1'}
        if not args.registry:
            return subprocess.Popen(command,cwd=ROOT,env=env)
        process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                 text=True,encoding='utf-8',errors='replace',bufsize=1)
        registered=threading.Event()
        def forward():
            with process.stdout:
                for line in process.stdout:
                    if line.startswith('[reg]') and 'pid=' in line:
                        registered.set()
                    print(line,end='',flush=True)
        process._audio_output_thread=threading.Thread(target=forward,daemon=True)
        process._audio_output_thread.start()
        if not registered.wait(10):
            if '--stop-file' in arguments:
                Path(arguments[arguments.index('--stop-file')+1]).touch()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                print(f'{name} did not stop after registration failure; inspect the process monitor.',flush=True)
            raise RuntimeError(f'{name} process registration did not complete')
        return process
    def wait_module(process):
        result=process.wait()
        output_thread=getattr(process,'_audio_output_thread',None)
        if output_thread: output_thread.join(timeout=2)
        return result
    children=[]
    stop_dir=Path(tempfile.mkdtemp(prefix='audio-memory-stop-'))
    recorder_stop=stop_dir/'recorder-stop'; transcriber_stop=stop_dir/'transcriber-stop'; bridge_stop=stop_dir/'bridge-stop'
    requested_stop=False
    bridge=None
    transcriber_reported=False
    try:
        recorder_args=['--out',str(data_root/'record'),'--device',args.device,'--stop-file',str(recorder_stop)]
        if args.ready_file: recorder_args += ['--ready-file',str(args.ready_file)]
        children.append(start_module('recorder','recorder.py',recorder_args))
        if args.mode=='cloud':
            children.append(start_module('transcriber','cloud_transcriber.py',['--root',str(data_root),'--config',str(args.cloud_config),'--stop-file',str(transcriber_stop)]))
        else:
            children.append(start_module('transcriber','transcriber.py',['--dir',str(data_root/'record'),'--out',str(data_root/'out'),'--model',args.model,'--stop-file',str(transcriber_stop)]))
        try:
            bridge=start_module('material-bridge','material_bridge.py',['--root',str(data_root),'--watch','--stop-file',str(bridge_stop)])
        except OSError as error:
            print('Material bridge unavailable; recording continues:',type(error).__name__,flush=True)
        print('Recording and '+args.mode+' transcription started; Ctrl+C stops this session.',flush=True)
        while True:
            if args.stop_file and args.stop_file.exists():
                requested_stop=True
                break
            result=children[0].poll()
            if result is not None:raise RuntimeError('Recorder exited with code '+str(result))
            transcriber_result=children[1].poll()
            if transcriber_result is not None and not transcriber_reported:
                print('Transcription stopped; recording continues. Saved audio can be retried.',flush=True)
                transcriber_reported=True
            if bridge is not None and bridge.poll() is not None:
                print('Material bridge stopped; recording continues. Run material_bridge.py later to recover.',flush=True)
                bridge=None
            time.sleep(1)
    except KeyboardInterrupt:
        requested_stop=True
        print('Stopping this session.',flush=True)
    finally:
        recorder_stop.touch()
        if children:
            print('Waiting for the recorder to save its last segment...',flush=True)
            wait_module(children[0])
        transcriber_stop.touch()
        if len(children)>1:
            if children[1].poll() is None:
                print('Waiting for transcription to finish its current segment...',flush=True)
            wait_module(children[1])
        if requested_stop and len(children)>1 and args.mode=='local':
            print('Checking saved audio for remaining transcription (up to 120 seconds)...',flush=True)
            command=[sys.executable,str(ROOT/'transcriber.py'),'--dir',str(data_root/'record'),'--out',str(data_root/'out'),'--model',args.model,'--once']
            try:
                result=subprocess.run(command,cwd=ROOT,timeout=120)
                if result.returncode:
                    print('Transcription did not finish; audio remains saved for retry.',flush=True)
            except subprocess.TimeoutExpired:
                print('Transcription timed out; audio remains saved for retry.',flush=True)
        if bridge is not None:
            bridge_stop.touch()
            wait_module(bridge)
        else:
            try:
                subprocess.run([sys.executable,str(ROOT/'material_bridge.py'),'--root',str(data_root)],cwd=ROOT,timeout=60,check=False)
            except (OSError, subprocess.TimeoutExpired):
                print('Material index unavailable; saved files can be indexed later.',flush=True)
        recorder_stop.unlink(missing_ok=True); transcriber_stop.unlink(missing_ok=True); bridge_stop.unlink(missing_ok=True); stop_dir.rmdir()

if __name__=='__main__':main()
