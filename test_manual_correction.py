import hashlib
import json
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from transcript_corrections import apply_manual_text, effective, load, publish_reviewed

class ManualCorrectionTests(unittest.TestCase):
    def test_annotation_service_checks_source_revision_and_utf16_selection(self):
        from transcript_corrections import annotation_action, record_key
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'out'/'day'/'timeline.jsonl';source.parent.mkdir(parents=True)
            row={'file':'x','start':0,'end':1,'text':'😀原文'};source.write_text(json.dumps(row,ensure_ascii=False)+'\n',encoding='utf-8')
            data={'source':str(source),'recordId':record_key(source,row),'original':row['text'],'text':row['text'],'revision':0,'selectionStartUtf16':2,'selectionLengthUtf16':2,'instruction':'修订','replacement':'修改'}
            note=annotation_action(root,'add',data);self.assertEqual(note['selected'],'原文')
            batch=annotation_action(root,'submit');self.assertEqual(load(root)['annotations'][0]['batchId'],batch)
            annotation_action(root,'fail',{'batch':batch,'error':'fixture'});self.assertEqual(load(root)['annotations'][0]['status'],'failed')
            annotation_action(root,'edit',{'id':note['id'],'instruction':'new','replacement':'新文'})
            annotation_action(root,'remove',{'id':note['id']});self.assertEqual(load(root)['annotations'],[])
            data['revision']=1
            with self.assertRaises(ValueError):annotation_action(root,'add',data)
            self.assertEqual(json.loads(source.read_text(encoding='utf-8'))['text'],'😀原文')

    def test_annotation_service_concurrent_submit_has_one_winner(self):
        from transcript_corrections import save
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);save({'schemaVersion':1,'records':{},'annotations':[{'id':'one','status':'draft'}]},root)
            command=[sys.executable,str(Path(__file__).with_name('transcript_corrections.py')),'--root',str(root),'--annotation-action','submit']
            processes=[subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
            for p in processes:p.stdin.write(b'{}');p.stdin.close();p.stdin=None
            for p in processes:p.communicate(timeout=15)
            self.assertEqual(sorted(p.returncode for p in processes),[0,1])
            self.assertEqual(load(root)['annotations'][0]['status'],'submitted')

    def test_annotation_cloud_request_uses_selected_data_root(self):
        from unittest.mock import patch
        from annotation_worker import generate
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            response={'choices':[{'finish_reason':'stop','message':{'content':'{"replacements":[{"id":"one","text":"fixed"}]}'}}]}
            with patch('annotation_worker.request',return_value=response) as request:
                replacements,_=generate({'file':'missing','text':'raw'},[{'id':'one','selected':'raw','instruction':'fix'}],root=root)
            self.assertEqual(replacements,{'one':'fixed'})
            self.assertEqual(request.call_args.kwargs['config_path'],root/'config'/'ark_config.json')

    def test_manual_correction_preserves_raw_and_rejects_stale_update(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'out'/'20261031'/'timeline.jsonl';source.parent.mkdir(parents=True)
            raw={'file':'test.wav','start':0,'end':1,'text':'😀试图','t':'10:00:00'}
            source.write_text(json.dumps(raw,ensure_ascii=False)+'\n',encoding='utf-8');original=source.read_bytes()
            version=hashlib.sha256(json.dumps(raw,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            result=apply_manual_text(root,source,1,version,'😀视图')
            self.assertEqual(result,{'changed':True,'revision':1});self.assertEqual(source.read_bytes(),original)
            state=load(root);self.assertEqual(effective(raw,source,state)['text'],'😀视图')
            self.assertEqual(state['annotations'][0]['selectionLengthUtf16'],4)
            with self.assertRaisesRegex(ValueError,'字幕已发生变化'):apply_manual_text(root,source,1,version,'过期覆盖')
            self.assertEqual(effective(raw,source,load(root))['text'],'😀视图')

    def test_relocated_correction_keeps_identity_annotations_and_raw_source(self):
        import shutil
        from transcript_corrections import record_key
        from material_snapshot import build
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder); old=base/'old'; new=base/'new'
            source=old/'out'/'20261031'/'timeline.jsonl'; source.parent.mkdir(parents=True)
            raw={'file':'test.wav','start':0,'end':1,'text':'原文'}
            source.write_text(json.dumps(raw,ensure_ascii=False)+'\n',encoding='utf-8')
            version=hashlib.sha256(json.dumps(raw,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            apply_manual_text(old,source,1,version,'首次修订')
            previous=load(old); identity=record_key(source,raw)
            new.mkdir(); shutil.copytree(old/'out',new/'out');shutil.copy2(old/'transcript-corrections.json',new/'transcript-corrections.json')
            moved=new/'out'/'20261031'/'timeline.jsonl'; self.assertEqual(effective(raw,moved,load(new))['text'],'首次修订')
            self.assertEqual(next(x for x in build(new,write=False)['materials'] if x['kind']=='transcript_segment')['preview'],'首次修订')
            from classroom_materials import publish
            page=publish(moved.parent,root=new)
            self.assertIn('首次修订',page.read_text(encoding='utf-8'))
            reviewed=moved.with_name('timeline.corrected.jsonl')
            self.assertEqual(json.loads(reviewed.read_text(encoding='utf-8'))['text'],'首次修订')
            current=effective(raw,moved,load(new)); current_version=hashlib.sha256(json.dumps(current,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            self.assertEqual(apply_manual_text(new,moved,1,current_version,'再次修订')['revision'],2)
            state=load(new);self.assertEqual(list(state['records']),[identity]);self.assertTrue(all(x['recordId']==identity for x in state['annotations']))
            self.assertEqual(json.loads(moved.read_text(encoding='utf-8'))['text'],'原文')
            self.assertEqual(load(old),previous)

    def test_ambiguous_relocated_records_are_rejected(self):
        from transcript_corrections import CorrectionConflict, record_key
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'out'/'day'/'timeline.jsonl';source.parent.mkdir(parents=True)
            row={'file':'x','start':0,'end':1,'text':'raw'}
            record={'sourceFile':'C:/old/out/day/timeline.jsonl','file':'x','start':0,'end':1,'original':'raw','text':'fixed','revision':1}
            state={'records':{'first':record,'second':dict(record)},'annotations':[]}
            with self.assertRaises(CorrectionConflict): effective(row,source,state)
            from transcript_corrections import save
            from material_snapshot import build
            from material_bridge import sync
            source.write_text(json.dumps(row)+'\n',encoding='utf-8');save(state,Path(folder))
            manifest=build(Path(folder),write=False)
            self.assertFalse([x for x in manifest['materials'] if x['kind']=='transcript_segment'])
            self.assertEqual(manifest['warnings'][0]['code'],'ambiguous_transcript_correction')
            report=sync(Path(folder));self.assertEqual(report['transcript'],0)
            self.assertTrue(any(error['kind']=='CorrectionConflict' for error in report['errors']))

    def test_outside_source_and_empty_replacement_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);other=root/'timeline.jsonl';other.write_text('{}',encoding='utf-8')
            with self.assertRaises(ValueError):apply_manual_text(root,other,1,'x','文字')
            source=root/'out'/'timeline.jsonl';source.parent.mkdir();source.write_text('{}',encoding='utf-8')
            with self.assertRaises(ValueError):apply_manual_text(root,source,1,'x','  ')


    def test_existing_corrected_file_is_backed_up_before_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'out'/'day'/'timeline.jsonl';source.parent.mkdir(parents=True)
            row={'file':'test.wav','start':0,'end':1,'text':'原稿'}
            source.write_text(json.dumps(row,ensure_ascii=False)+'\n',encoding='utf-8')
            corrected=source.with_name('timeline.corrected.jsonl');corrected.write_text('手工保留内容',encoding='utf-8')
            result=publish_reviewed(source,root)
            backups=list((root/'backups'/'transcript-corrections').glob('*.jsonl'))
            self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_text(encoding='utf-8'),'手工保留内容')
            self.assertEqual(json.loads(result.read_text(encoding='utf-8'))['text'],'原稿')
            publish_reviewed(source,root)
            self.assertEqual(len(list((root/'backups'/'transcript-corrections').glob('*.jsonl'))),1)

if __name__=='__main__':unittest.main()
