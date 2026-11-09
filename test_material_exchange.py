import json
from pathlib import Path
import tempfile
import unittest
from material_exchange import MaterialExchange


class ExchangeTests(unittest.TestCase):
    def test_workbench_snapshot_reads_relocated_revision_via_material_service(self):
        import datetime,time
        from material_snapshot import workbench_snapshot
        from transcript_corrections import save
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);day=datetime.datetime.now().strftime('%Y%m%d');source=root/'out'/day/'timeline.jsonl';source.parent.mkdir(parents=True)
            row={'t':'10:00','file':'fixture','start':0,'end':1,'text':'😀原文'};source.write_text(json.dumps(row,ensure_ascii=False)+'\n',encoding='utf-8')
            record={'id':'old-id','sourceFile':'D:/old/out/'+day+'/timeline.jsonl','file':'fixture','start':0,'end':1,'original':'😀原文','text':'😀修订','revision':1}
            save({'schemaVersion':1,'records':{'old-id':record},'annotations':[]},root)
            snapshot=workbench_snapshot(root,'transcriber.stdout.log',time.time())
            self.assertIn('😀修订',snapshot['Transcript']);self.assertEqual(snapshot['Ranges'][0]['Id'],'old-id')
            self.assertEqual(snapshot['Ranges'][0]['DisplayLength'],4)
            (root/'transcription-control.json').write_text(json.dumps({'mode':'cloud','deadline':time.time()-1}),encoding='utf-8')
            self.assertEqual(workbench_snapshot(root,'transcriber.stdout.log',time.time())['Mode'],'local')
            with self.assertRaises(ValueError):workbench_snapshot(root,'../private.log',time.time())

    def test_material_discovery_rejects_files_outside_data_root(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside:
            root=Path(folder); external=Path(outside)
            live=external/'live-materials'/'day'/'当前课堂实时材料.md';live.parent.mkdir(parents=True);live.write_text('private',encoding='utf-8')
            catalog=external/'ppt-concepts'/'catalog.json';catalog.parent.mkdir(parents=True);catalog.write_text('{}',encoding='utf-8')
            exchange=MaterialExchange(root,transcripts=external)
            self.assertEqual(exchange.live_materials(),[])
            with self.assertRaises(ValueError):exchange.ocr_catalog()

    def test_gateway_snapshot_uses_replaced_storage_layout(self):
        from material_snapshot import ManifestBuilder
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); output=root/'alternate'; device='a'*32; item='b'*32
            audio=output/'mobile-sync'/device/item/'audio.wav'; audio.parent.mkdir(parents=True); audio.write_bytes(b'audio')
            (audio.parent/'metadata.json').write_text(json.dumps({'id':item,'deviceId':device,'sha256':'test','startedAt':'2026-11-09T10:00:00+08:00'}),encoding='utf-8')
            frame=output/'scene'/'frames'/'one.png'; frame.parent.mkdir(parents=True); frame.write_bytes(b'frame')
            exchange=MaterialExchange(root,transcripts=output)
            snapshot=ManifestBuilder(root,exchange).build()
            self.assertEqual({x['kind'] for x in snapshot['materials']},{'audio','scene_frame'})
            self.assertFalse((root/'out').exists())

    def test_alternate_layout_keeps_consumers_independent_of_legacy_directories(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / 'new-audio-layout'; audio.mkdir()
            (audio / '20261108_100000_0001.wav').write_bytes(b'test')
            output = root / 'new-transcript-layout'
            store = MaterialExchange(root, recordings=audio, transcripts=output)
            self.assertEqual(len(store.recordings()), 1)
            store.append_transcripts('20261108', [{'text': 'example'}])
            store.append_transcripts('20261108', [{'text': 'cloud'}], cloud=True)
            self.assertEqual(json.loads((output / '20261108' / 'timeline.jsonl').read_text(encoding='utf-8'))['text'], 'example')
            self.assertEqual(json.loads((output / 'cloud-asr-20261108' / 'timeline.jsonl').read_text(encoding='utf-8'))['text'], 'cloud')
            self.assertFalse((root / 'record').exists())
            self.assertFalse((root / 'out').exists())
            with self.assertRaises(ValueError): store.append_transcripts('../escape', [{}])

    def test_classroom_package_survives_move_and_rejects_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); base=root/'out'/'classroom-bridge'; session=base/'session-1';session.mkdir(parents=True)
            (session/'notes-input.json').write_text(json.dumps({'schema':'fixture'}),encoding='utf-8')
            latest=base/'latest.json'
            latest.write_text(json.dumps({'status':'ready_for_notes','sessionId':'session-1','path':'C:/old/location/notes-input.json'}),encoding='utf-8')
            path, data=MaterialExchange(root).classroom_package()
            self.assertEqual(data['schema'],'fixture');self.assertEqual(path,(session/'notes-input.json').resolve())
            (session/'notes-input.json').write_text(json.dumps({'video':{'id':'different'}}),encoding='utf-8')
            with self.assertRaises(ValueError): MaterialExchange(root).classroom_package()
            latest.write_text(json.dumps({'status':'ready_for_notes','sessionId':'../../escape'}),encoding='utf-8')
            with self.assertRaises(ValueError): MaterialExchange(root).classroom_package()

    def test_visual_ingestion_uses_alternate_material_layout(self):
        from material_bridge import sync
        from material_store import list_materials
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=root/'new-store';slide=store/'scene'/'ppt'/'run'/'slide.png'
            slide.parent.mkdir(parents=True);slide.write_bytes(b'image')
            (slide.parent/'index.json').write_text(json.dumps({'items':[{'id':'one','path':str(slide)}]}),encoding='utf-8')
            report=sync(root,visual_only=True,exchange=MaterialExchange(root,transcripts=store))
            self.assertEqual((report['slides'],report['errors']),(1,[]))
            self.assertEqual(list_materials(root,kind='ppt_slide')['total'],1)

    def test_ingestion_rejects_custom_transcript_directory_outside_root(self):
        from material_bridge import sync
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as external:
            root=Path(folder);outside=Path(external);(outside/'timeline.jsonl').write_text('{"text":"private"}\n',encoding='utf-8')
            exchange=MaterialExchange(root,transcripts=outside)
            report=sync(root,exchange=exchange)
            self.assertEqual(report['transcript'],0)
            self.assertTrue(any(x['kind']=='transcript_source_outside_project' for x in report['errors']))
            with self.assertRaises(ValueError): exchange.recording_receipt()
            self.assertTrue(any(x['kind']=='SourceOutsideProject' for x in report['errors']))

    def test_old_transcript_path_rebind_requires_explicit_compatibility_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'out'/'day'/'timeline.jsonl';source.parent.mkdir(parents=True);source.write_text('{}',encoding='utf-8')
            exchange=MaterialExchange(root);old='C:/previous/out/day/timeline.jsonl'
            with self.assertRaises(ValueError): exchange.transcript_source(old)
            self.assertEqual(exchange.transcript_source(old,allow_relocated=True),source.resolve())
            with self.assertRaises(ValueError): exchange.transcript_source('C:/previous/out/../escape/timeline.jsonl',allow_relocated=True)

    def test_audio_lookup_confines_recording_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);recordings=root/'media';recordings.mkdir();audio=recordings/'sample.wav';audio.write_bytes(b'audio')
            exchange=MaterialExchange(root,recordings=recordings)
            self.assertEqual(exchange.audio_for_stem('sample'),audio.resolve())
            self.assertIsNone(exchange.audio_for_stem('missing'))
            with self.assertRaises(ValueError): exchange.audio_for_stem('../escape')

    def test_video_discovery_and_access_confines_material_root(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside:
            root = Path(folder); camera = root / 'custom' / 'camera'; camera.mkdir(parents=True)
            video = camera / 'complete.webm'; video.write_bytes(b'video')
            (camera / 'capture.partial.webm').write_bytes(b'incomplete')
            other = Path(outside) / 'other.webm'; other.write_bytes(b'outside')
            store = MaterialExchange(root, recordings=camera.parent)
            self.assertEqual([x.name for x in store.videos()], ['complete.webm'])
            self.assertEqual(store.video_source(video)[1], 'custom/camera/complete.webm')
            with self.assertRaises(ValueError): store.video_source(other)
            with self.assertRaises(ValueError): store.video_source(camera / 'capture.partial.webm')

    def test_transcriber_uses_replaced_storage_layout(self):
        import sys
        import wave
        from types import SimpleNamespace
        from unittest.mock import patch
        import transcriber
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); audio_dir = root / 'media' / 'input'; audio_dir.mkdir(parents=True)
            output_dir = root / 'media' / 'subtitles'
            audio = audio_dir / '20261108_100000_0001.wav'
            with wave.open(str(audio), 'wb') as output:
                output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000); output.writeframes(b'\x01\x00' * 16000)
            exchange = MaterialExchange(root, recordings=audio_dir, transcripts=output_dir)
            class Model:
                def __init__(self, *args, **kwargs):
                    self.cache = kwargs['download_root']
                    if self.cache != str(root / 'models' / 'asr-cache'): raise AssertionError(self.cache)
                def transcribe(self, *args, **kwargs):
                    return iter([SimpleNamespace(start=0, end=1, text='example')]), None
            args = ['transcriber.py', '--root', str(root), '--once', '--backfill-days', '0', '--min-mb', '0']
            with patch.object(sys, 'argv', args), patch.object(transcriber, 'MaterialExchange', return_value=exchange), \
                 patch.object(transcriber, 'WhisperModel', Model), patch.object(transcriber, 'postproc', side_effect=lambda value: value):
                transcriber.main()
            self.assertEqual(json.loads((output_dir / '20261108' / 'timeline.jsonl').read_text(encoding='utf-8'))['text'], 'example')
            self.assertFalse((root / 'record').exists())

    def test_recording_to_transcript_to_index_survives_reopen(self):
        import sys
        import wave
        from types import SimpleNamespace
        from unittest.mock import patch
        import transcriber
        from material_bridge import sync
        from material_store import list_materials, read_material
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); recordings = root / 'record'; recordings.mkdir()
            audio = recordings / '20261108_100000_0001.wav'
            with wave.open(str(audio), 'wb') as out:
                out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000); out.writeframes(b'\x01\x00' * 16000)
            class Model:
                def __init__(self, *args, **kwargs): pass
                def transcribe(self, *args, **kwargs):
                    return iter([SimpleNamespace(start=0, end=1, text=' testing ')]), None
            args = ['transcriber.py', '--dir', str(recordings), '--out', str(root / 'out'), '--once', '--backfill-days', '0', '--min-mb', '0']
            with patch.object(sys, 'argv', args), patch.object(transcriber, 'WhisperModel', Model), patch.object(transcriber, 'postproc', side_effect=lambda value: value):
                transcriber.main()
            report = sync(root)
            self.assertEqual((report['audio'], report['transcript'], report['errors']), (1, 1, []))
            item = list_materials(root, kind='transcript_segment')['items'][0]
            self.assertEqual(read_material(item['id'], root)[1]['text'], 'testing')
            with patch.object(sys, 'argv', args), patch.object(transcriber, 'WhisperModel', side_effect=AssertionError('already processed')):
                transcriber.main()
            self.assertEqual(list_materials(root, kind='transcript_segment')['total'], 1)


if __name__ == '__main__': unittest.main()
