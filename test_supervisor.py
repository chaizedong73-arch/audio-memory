import tempfile
import json
import os
import shutil
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
import numpy as np
import recorder
import run_core
import transcriber

class StopTests(unittest.TestCase):
    def test_failed_transcriber_does_not_stop_recorder(self):
        instances=[]
        class Child:
            def __init__(self, args, **kwargs):
                self.kind='recorder' if 'recorder.py' in args[1] else ('bridge' if 'material_bridge.py' in args[1] else 'transcriber')
                self.stop=Path(args[args.index('--stop-file')+1]); instances.append(self)
            def poll(self): return 7 if self.kind=='transcriber' else None
            def wait(self): self.stop.exists()
        with patch('sys.argv',['run_core.py']), patch.object(run_core.subprocess,'Popen',Child), \
             patch.object(run_core.subprocess,'run',return_value=type('Result',(),{'returncode':0})()), \
             patch.object(run_core.time,'sleep',side_effect=KeyboardInterrupt):
            run_core.main()
        self.assertEqual([x.kind for x in instances],['recorder','transcriber','bridge'])

    def test_database_failure_does_not_lose_recording(self):
        with tempfile.TemporaryDirectory() as folder:
            stop=Path(folder)/'stop'; output=Path(folder)/'audio'
            class Stream:
                def __init__(self, **kwargs): self.callback=kwargs['callback']
                def __enter__(self):
                    self.callback(np.ones((400,1),dtype=np.float32)*0.1,400,None,None)
                    stop.touch(); return self
                def __exit__(self,*args): return False
            with patch('sys.argv',['recorder.py','--device','0','--sr','16000','--seconds','5','--out',str(output),'--stop-file',str(stop)]), \
                 patch.object(recorder.sd,'InputStream',Stream), patch('material_store.register_material',side_effect=RuntimeError('test')):
                recorder.main()
            self.assertEqual(len(list(output.glob('*.wav'))),1)

    def test_recorder_finishes_before_transcriber_stops_and_drain_starts(self):
        events=[]
        class Child:
            def __init__(self, args, **kwargs):
                self.kind='recorder' if 'recorder.py' in args[1] else ('bridge' if 'material_bridge.py' in args[1] else 'transcriber')
                self.stop=Path(args[args.index('--stop-file')+1])
                events.append(self)
            def poll(self): return None
            def wait(self):
                self.assert_stopped()
                if self.kind == 'recorder':
                    assert not events[1].stop.exists()
            def assert_stopped(self): assert self.stop.exists()
        def drain(args, **kwargs):
            assert events[0].stop.exists() and events[1].stop.exists()
            assert '--once' in args
            return type('Result', (), {'returncode': 0})()
        with patch('sys.argv',['run_core.py']), patch.object(run_core.subprocess,'Popen',Child), \
             patch.object(run_core.subprocess,'run',side_effect=drain), patch.object(run_core.time,'sleep',side_effect=KeyboardInterrupt):
            run_core.main()

    def test_stop_signal_flushes_pending_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            stop=Path(folder)/'stop'; output=Path(folder)/'audio'
            class Stream:
                def __init__(self, **kwargs): self.callback=kwargs['callback']
                def __enter__(self):
                    self.callback(np.ones((400,1),dtype=np.float32)*0.1,400,None,None)
                    stop.touch(); return self
                def __exit__(self,*args):return False
            with patch('sys.argv',['recorder.py','--device','0','--sr','16000','--seconds','5','--out',str(output),'--stop-file',str(stop)]), patch.object(recorder.sd,'InputStream',Stream):
                recorder.main()
            files=list(output.glob('*.wav'))
            self.assertEqual(len(files),1)
            with wave.open(str(files[0])) as sample:self.assertEqual(sample.getnframes(),400)


    def test_custom_data_root_routes_all_children_without_touching_code_root(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder).resolve(); commands=[]
            class Child:
                def __init__(self,args,**kwargs): self.args=args; commands.append(args)
                def poll(self): return None
                def wait(self): pass
            with patch('sys.argv',['run_core.py','--root',str(data)]), patch.object(run_core.subprocess,'Popen',Child), \
                 patch.object(run_core.subprocess,'run',return_value=type('Result',(),{'returncode':0})()), \
                 patch.object(run_core.time,'sleep',side_effect=KeyboardInterrupt):
                run_core.main()
            self.assertIn('--root',commands[0]); self.assertIn(str(data),commands[0])
            self.assertIn('--root',commands[1]); self.assertIn(str(data),commands[1])
            self.assertIn(str(data),commands[2])


    @unittest.skipUnless(shutil.which('node'),'Node required for process registration')
    def test_registered_children_exit_and_unregister_on_stop(self):
        with tempfile.TemporaryDirectory(prefix='audio-supervisor-test-') as folder:
            data=Path(folder).resolve()
            self.assertEqual(data.parent,Path(tempfile.gettempdir()).resolve())
            program=data/'program';program.mkdir()
            script="""import sys,time
from pathlib import Path
if '--once' not in sys.argv:
 p=Path(sys.argv[sys.argv.index('--stop-file')+1])
 while not p.exists():time.sleep(.05)
"""
            for name in ('recorder.py','transcriber.py','material_bridge.py'):(program/name).write_text(script,encoding='utf-8')
            stop=data/'stop';stop.touch();registry=data/'registry'
            command=['run_core.py','--root',str(data),'--stop-file',str(stop),'--registry',str(run_core.ROOT/'desktop'/'registry.mjs'),'--registry-executable',shutil.which('node')]
            with patch.object(run_core,'ROOT',program), patch('sys.argv',command), patch.dict(os.environ,{'AUDIO_MEMORY_PROCESS_REGISTRY_DIR':str(registry)}):
                run_core.main()
            entries=json.loads((registry/'process-registry.json').read_text(encoding='utf-8'))['processes']
            self.assertEqual(len(entries),3)
            self.assertTrue(all(row['status']=='exited' for row in entries))


    def test_recording_ready_requires_audio_and_is_removed_after_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);stop=root/'stop';ready=root/'ready';out=root/'audio';observed=[]
            class Stream:
                def __init__(self,**kwargs):self.callback=kwargs['callback']
                def __enter__(self):self.callback(np.ones((400,1),dtype=np.float32)*0.1,400,None,None);stop.touch();return self
                def __exit__(self,*args):observed.append(ready.exists());return False
            with patch('sys.argv',['recorder.py','--device','0','--sr','16000','--seconds','5','--out',str(out),'--stop-file',str(stop),'--ready-file',str(ready)]), patch.object(recorder.sd,'InputStream',Stream):recorder.main()
            self.assertEqual(observed,[True]);self.assertFalse(ready.exists());self.assertEqual(len(list(out.glob('*.wav'))),1)

    def test_device_failure_honours_stop_without_ready_signal(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);stop=root/'stop';ready=root/'ready';out=root/'audio'
            class Stream:
                def __init__(self,**kwargs):pass
                def __enter__(self):stop.touch();raise OSError('simulated device loss')
                def __exit__(self,*args):return False
            with patch('sys.argv',['recorder.py','--device','0','--sr','16000','--seconds','5','--out',str(out),'--stop-file',str(stop),'--ready-file',str(ready)]), patch.object(recorder.sd,'InputStream',Stream):recorder.main()
            self.assertFalse(ready.exists());self.assertEqual(list(out.glob('*.wav')),[])


    def test_recording_ready_clears_when_audio_callback_stalls(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);stop=root/'stop';ready=root/'ready';out=root/'audio';observed=[]
            class Stream:
                def __init__(self,**kwargs):self.callback=kwargs['callback'];self.timer=None
                def __enter__(self):
                    self.callback(np.ones((400,1),dtype=np.float32)*0.1,400,None,None)
                    self.timer=threading.Timer(5.7,stop.touch);self.timer.start();return self
                def __exit__(self,*args):observed.append(ready.exists());self.timer.join();return False
            with patch('sys.argv',['recorder.py','--device','0','--sr','16000','--seconds','10','--out',str(out),'--stop-file',str(stop),'--ready-file',str(ready)]), patch.object(recorder.sd,'InputStream',Stream):recorder.main()
            self.assertEqual(observed,[False]);self.assertEqual(len(list(out.glob('*.wav'))),1)


    def test_transcriber_lock_follows_custom_data_root(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder).resolve()
            with patch('sys.argv',['transcriber.py','--dir',str(data/'record'),'--out',str(data/'out'),'--once']), \
                 patch('singlelock.acquire',return_value=None) as acquire:
                transcriber.main()
            acquire.assert_called_once_with(str(data/'.locks'/'transcriber.lock'))


    def test_stop_before_parent_registration_does_not_start_children(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); stop=root/'stop';stop.touch()
            with patch('sys.argv',['run_core.py','--root',str(root),'--stop-file',str(stop),'--parent-registered-file',str(root/'not-ready')]), \
                 patch.object(run_core.subprocess,'Popen') as spawn:
                run_core.main()
            spawn.assert_not_called()

if __name__=='__main__':unittest.main()
