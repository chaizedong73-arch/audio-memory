import io
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
import wave
import zipfile
from mobile_sync import import_package
from ai_material_gateway import build
from audio_memory_mcp import Client, dispatch


def package(text='课堂测试：明天九点开会',identity='a'*32,updated='2026-11-06T01:00:00Z',hash_bad=False):
    audio=io.BytesIO()
    with wave.open(audio,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\x01\x00'*16000)
    raw=audio.getvalue();meta={'id':identity,'deviceId':'b'*32,'startedAt':'2026-11-06T00:00:00Z','updatedAt':updated,'text':text,'sha256':'wrong' if hash_bad else hashlib.sha256(raw).hexdigest(),'model':'test'}
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:z.writestr('metadata.json',json.dumps(meta));z.writestr('audio.wav',raw)
    return out.getvalue()


class MobileSyncTests(unittest.TestCase):
    def test_import_repeat_update_and_materials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.assertFalse(import_package(root,package())['duplicate']);self.assertTrue(import_package(root,package())['duplicate'])
            manifest=build(root,write=False);self.assertEqual(len(manifest['materials']),2)
            self.assertEqual({x['kind'] for x in manifest['materials']},{'audio','transcript_segment'})
            transcript=next(x for x in manifest['materials'] if x['kind']=='transcript_segment');old_id=transcript['id']
            import_package(root,package(text='修订文本',updated='2026-11-06T02:00:00Z'))
            second=build(root,write=False);new=next(x for x in second['materials'] if x['kind']=='transcript_segment')
            self.assertEqual(old_id,new['id']);self.assertEqual(new['preview'],'修订文本')
            with self.assertRaises(FileExistsError):import_package(root,package())
            self.assertEqual(len(list(root.rglob('audio.wav'))),1)

    def test_http_receipt_signals_pending_and_retry_clears_it(self):
        from unittest.mock import patch
        from http.server import ThreadingHTTPServer
        from urllib.request import Request, urlopen
        import threading
        from mobile_sync import make_handler
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(root,'fixture-token'))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            url=f'http://127.0.0.1:{server.server_port}/v1/sync/recordings'
            def send():
                request=Request(url,data=package(),headers={'Authorization':'Bearer fixture-token','Content-Type':'application/zip'})
                with urlopen(request,timeout=5) as response:return json.load(response)
            try:
                with patch('material_ingest.ingest_recordings_and_transcripts',side_effect=OSError('index offline')):
                    first=send()
                self.assertEqual(first['status'],'saved');self.assertTrue(first['indexPending'])
                second=send();self.assertTrue(second['duplicate']);self.assertFalse(second['indexPending'])
            finally:
                server.shutdown();server.server_close();thread.join()

    def test_import_indexes_immediately_and_recovers_after_index_failure(self):
        from unittest.mock import patch
        from material_store import list_materials
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch('material_ingest.ingest_recordings_and_transcripts',side_effect=OSError('index unavailable')):
                first=import_package(root,package())
            self.assertTrue(first['indexPending'])
            original=next(root.rglob('audio.wav')).read_bytes()
            retry=import_package(root,package())
            self.assertTrue(retry['duplicate']);self.assertFalse(retry['indexPending'])
            self.assertEqual(list_materials(root,kind='audio')['total'],1)
            self.assertEqual(list_materials(root,kind='transcript_segment')['total'],1)
            self.assertEqual(next(root.rglob('audio.wav')).read_bytes(),original)

    def test_receiver_accepts_alternate_storage_without_layout_knowledge(self):
        from unittest.mock import patch
        from material_exchange import MaterialExchange
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); store = MaterialExchange(root, transcripts=root / 'new-storage')
            with patch('mobile_sync.MaterialExchange', return_value=store):
                self.assertFalse(import_package(root, package())['duplicate'])
                self.assertTrue(import_package(root, package())['duplicate'])
            self.assertEqual(len(list((root / 'new-storage').rglob('audio.wav'))), 1)
            from material_bridge import sync
            report=sync(root,exchange=store)
            self.assertEqual((report['audio'],report['transcript'],report['errors']),(1,1,[]))
            from material_store import list_materials
            self.assertEqual(list_materials(root,kind='audio')['total'],1)

    def test_hash_and_path_rejection_preserve_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for blob in [package(hash_bad=True),package(identity='../'+'a'*29)]:
                with self.assertRaises(ValueError):import_package(root,blob)
            self.assertFalse((root/'out').exists())
            malicious=io.BytesIO()
            with zipfile.ZipFile(malicious,'w') as z:z.writestr('../escape','x')
            with self.assertRaises(ValueError):import_package(root,malicious.getvalue())

    def test_interrupted_import_never_reuses_different_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); folder = root/'out'/'mobile-sync'/('b'*32)/('a'*32)
            folder.mkdir(parents=True); original = b'previous incomplete import'
            (folder/'audio.wav').write_bytes(original)
            with self.assertRaises(FileExistsError): import_package(root,package())
            self.assertEqual((folder/'audio.wav').read_bytes(),original)
            self.assertFalse((folder/'metadata.json').exists())

    def test_same_version_conflict_is_not_silent_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            import_package(tmp,package())
            with self.assertRaises(FileExistsError):import_package(tmp,package(text='conflicting'))

    def test_mcp_protocol_has_only_read_tools_and_no_notification_reply(self):
        client=Client('.')
        init=dispatch({'id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18'}},client)
        self.assertEqual(init['result']['protocolVersion'],'2025-06-18')
        tools=dispatch({'id':2,'method':'tools/list'},client)['result']['tools'];self.assertEqual(len(tools),2)
        self.assertTrue(all(t['annotations']['readOnlyHint'] for t in tools))
        self.assertIsNone(dispatch({'method':'notifications/initialized'},client))
        self.assertTrue(dispatch({'id':3,'method':'tools/call','params':{'name':'read_recording_material','arguments':{'id':'../x'}}},client)['result']['isError'])


if __name__=='__main__':unittest.main()
