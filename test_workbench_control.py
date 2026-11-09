import tempfile
import unittest
import uuid
import json
import os
import shutil
import subprocess
import sys
from unittest.mock import patch
from pathlib import Path
from workbench_control import execute


class WorkbenchControlTests(unittest.TestCase):
    def test_context_credential_defaults_to_selected_data_root(self):
        from context_candidate_generator import key_file
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{},clear=True):
            root=Path(folder).resolve()
            self.assertEqual(key_file(root),root/'config'/'zhipu_api_key')
            with patch.dict(os.environ,{'ZHIPU_API_KEY_FILE':str(root/'explicit')}):self.assertEqual(key_file(root),root/'explicit')

    def test_subtitle_decision_accepts_private_stdin_without_request_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);reviews=root/'subtitle-reviews.json'
            reviews.write_text(json.dumps({'items':{'one':{'id':'one','status':'needs_confirmation'}}}),encoding='utf-8')
            script=Path(__file__).with_name('subtitle_decisions.py')
            subprocess.run([sys.executable,str(script),'--root',str(root),'--stdin'],input=json.dumps({'id':'one','action':'reject'}),text=True,encoding='utf-8',capture_output=True,check=True)
            self.assertEqual(json.loads(reviews.read_text(encoding='utf-8'))['items']['one']['status'],'rejected')
            self.assertFalse((root/'out'/'subtitle-decisions').exists())

    @unittest.skipUnless(shutil.which('node'),'Node is required for the workbench process registry')
    def test_registered_subtitle_process_receives_private_stdin_and_unregisters(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);reviews=root/'subtitle-reviews.json'
            reviews.write_text(json.dumps({'items':{'one':{'id':'one','status':'needs_confirmation'}}}),encoding='utf-8')
            registry=Path(__file__).parent/'desktop'/'registry.mjs';script=Path(__file__).with_name('subtitle_decisions.py')
            env={**os.environ,'AUDIO_MEMORY_PROCESS_REGISTRY_DIR':str(root/'registry'),'PYTHONUTF8':'1'}
            command=[shutil.which('node'),str(registry),'run','--owner','GPT','--name','Subtitle-Test','--desc','fixture','--',sys.executable,str(script),'--root',str(root),'--stdin']
            subprocess.run(command,input=json.dumps({'id':'one','action':'reject'}),text=True,encoding='utf-8',capture_output=True,check=True,env=env,timeout=15)
            self.assertEqual(json.loads(reviews.read_text(encoding='utf-8'))['items']['one']['status'],'rejected')
            entries=json.loads((root/'registry'/'process-registry.json').read_text(encoding='utf-8'))['processes']
            self.assertEqual(entries[-1]['status'],'exited')

    def test_controls_remain_inside_selected_root_and_stop_notes_on_classroom_end(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);notes=root/'notes';notes.mkdir()
            self.assertFalse(execute(root,'classroom-read'))
            config={'enabled':True,'notesRoot':str(notes),'description':'fixture','sessionId':str(uuid.uuid4())}
            with self.assertRaises(ValueError):execute(root,'notes-save',config)
            execute(root,'classroom-set',{'enabled':True});execute(root,'notes-save',config)
            self.assertTrue(execute(root,'notes-read')['enabled'])
            execute(root,'classroom-set',{'enabled':False});self.assertFalse(execute(root,'notes-read')['enabled'])
            execute(root,'subtitle-save',{'enabled':True});self.assertTrue(execute(root,'subtitle-read')['enabled'])
            execute(root,'transcription-set',{'mode':'local'});self.assertEqual(execute(root,'transcription-read')['mode'],'local')
            with self.assertRaises(ValueError):execute(root,'transcription-set',{'mode':'unexpected'})
            with self.assertRaises(ValueError):execute(root,'read-arbitrary-file')

    def test_notes_job_status_exposes_only_known_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);host=root/'host';host.mkdir();(host/'AiWorkbench.Contracts.dll').write_bytes(b'fixture')
            job='classroom-'+'a'*32;receipt=host/'modules'/'collaboration-canvas'/'data'/'workbuddy-dispatch'/(job+'.json');receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({'state':'waiting-permission','private':'never returned'}),encoding='utf-8')
            self.assertEqual(execute(root,'notes-job',{'hostRoot':str(host),'job':job}),'waiting-permission')
            self.assertEqual(execute(root,'notes-job',{'hostRoot':str(host),'job':'../../private'}),'')


if __name__=='__main__': unittest.main()
