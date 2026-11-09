from classroom_mode import set_enabled
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import uuid
from notes_maintenance import collect, prompt, run_batch, note_snapshot, changed_notes


class NotesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);set_enabled(self.root,True);self.notes=self.root/'notes';self.notes.mkdir()
        self.config={'notesRoot':str(self.notes),'description':'保留PPT骨架，先建后补也要衔接','strategy':'auto','sessionId':str(uuid.uuid4())}
        self.rows=[{'key':'one','hash':'v1','text':'老师解释SQL排序','file':'audio','t':'12:00:00','start':1,'end':2,'source':'fixture'}]
    def tearDown(self):self.temp.cleanup()
    def test_prompt_supports_both_modes_and_scaffold_changes(self):
        text,rows=prompt(self.config,self.rows,['数据库管理/排序.md'])
        self.assertIn('先识别课程',text);self.assertIn('图片',text);self.assertIn('重新读取笔记',text)
        self.assertIn('08-功能模组.md',text);self.assertIn('数据库管理/排序.md',text);self.assertEqual(len(rows),1)
    def test_new_slide_detected_but_new_plain_note_does_not_trigger_reflow(self):
        file=self.notes/'课堂.md';file.write_text('# 课堂\n先整理知识',encoding='utf-8')
        first=note_snapshot(self.notes)
        self.assertEqual(changed_notes({},first,True),[])
        file.write_text('# 课堂\n![[slide-01.png]]\n先整理知识',encoding='utf-8')
        second=note_snapshot(self.notes,first)
        self.assertEqual(changed_notes(first,second,True),['课堂.md'])
        self.assertEqual(changed_notes(second,note_snapshot(self.notes,second)),[])
    def test_missing_context_and_unverifiable_paths_do_not_advance(self):
        reply=self.root/'reply.md'
        def runner(*args,**kwargs):return subprocess.CompletedProcess([],0,json.dumps({'state':'finished','historyConfirmed':True,'replyFile':str(reply)}),'')
        reply.write_text(json.dumps({'status':'needs_context','files':[],'summary':'请提供本节课的课程'}),encoding='utf-8')
        report,done=run_batch(self.config,self.rows,Path('bridge.mjs'),self.root,runner)
        self.assertEqual(report['state'],'needs-context');self.assertEqual(done,{})
        outside=self.root/'unrelated.md';outside.write_text('outside')
        reply.write_text(json.dumps({'status':'updated','files':[str(outside)],'summary':'updated'}),encoding='utf-8')
        report,done=run_batch(self.config,self.rows,Path('bridge.mjs'),self.root,runner)
        self.assertEqual(report['state'],'uncertain');self.assertEqual(done,{})
    def test_only_confirmed_delegate_receipt_advances_progress(self):
        reply=self.root/'reply.md';reply.write_text(json.dumps({'status':'no_change','files':[],'summary':'已有内容覆盖该知识'}),encoding='utf-8')
        def runner(*args,**kwargs):return subprocess.CompletedProcess([],0,json.dumps({'state':'finished','historyConfirmed':True,'replyFile':str(reply)}),'')
        _,done=run_batch(self.config,self.rows,Path('bridge.mjs'),self.root,runner)
        self.assertEqual(done,{'one':'v1'})
        def uncertain(*args,**kwargs):return subprocess.CompletedProcess([],1,json.dumps({'state':'uncertain'}),'')
        _,done=run_batch(self.config,self.rows,Path('bridge.mjs'),self.root,uncertain)
        self.assertEqual(done,{})
    def test_collect_deduplicates_and_applies_transcript_corrections(self):
        import datetime as dt
        day=self.root/'out'/dt.datetime.now().strftime('%Y%m%d');day.mkdir(parents=True)
        row={'file':'audio','start':1,'end':2,'ts':time.time(),'text':'课堂内容'}
        (day/'timeline.jsonl').write_text(json.dumps(row,ensure_ascii=False)+'\n',encoding='utf-8')
        rows=collect(self.root,time.time()-10,{})
        self.assertEqual(rows[0]['text'],'课堂内容')
        self.assertEqual(collect(self.root,time.time()-10,{rows[0]['key']:rows[0]['hash']}),[])
        from transcript_corrections import record_key,save
        source=day/'timeline.jsonl';key=record_key(source,row)
        save({'records':{key:{'sourceFile':str(source),'original':'课堂内容','text':'已修订的课堂内容','revision':1}},'annotations':[]},self.root)
        self.assertEqual(collect(self.root,time.time()-10,{})[0]['text'],'已修订的课堂内容')
    def test_direct_cloud_transcriber_output_is_collected(self):
        import datetime as dt
        day=dt.datetime.now().strftime('%Y%m%d'); target=self.root/'out'/('cloud-asr-'+day)
        target.mkdir(parents=True)
        row={'file':'cloud','start':1,'end':2,'ts':time.time(),'text':'云端字幕'}
        (target/'timeline.jsonl').write_text(json.dumps(row,ensure_ascii=False)+'\n',encoding='utf-8')
        self.assertEqual([x['text'] for x in collect(self.root,time.time()-10,{})], ['云端字幕'])

    def test_cloud_quality_does_not_hide_unprocessed_local_material(self):
        import datetime as dt
        day=dt.datetime.now().strftime('%Y%m%d');local=self.root/'out'/day;cloud=self.root/'out'/'cloud-asr-fixture'/day
        local.mkdir(parents=True);cloud.mkdir(parents=True)
        first={'file':'one','start':1,'end':2,'ts':time.time(),'text':'本地原稿'}
        second={**first,'file':'two','text':'仅本地的另一段'}
        (local/'timeline.jsonl').write_text(json.dumps(first)+'\n'+json.dumps(second)+'\n')
        (cloud/'timeline.jsonl').write_text(json.dumps({**first,'text':'云端更准确的版本'})+'\n')
        rows=collect(self.root,time.time()-10,{})
        self.assertEqual({r['file']:r['text'] for r in rows},{'one':'云端更准确的版本','two':'仅本地的另一段'})
    def test_scaffold_change_without_new_audio_is_maintained(self):
        from unittest.mock import patch
        from notes_maintenance import watch,save,read
        note=self.notes/'课堂.md';note.write_text('# 课堂\n已有内容',encoding='utf-8')
        config={**self.config,'enabled':True,'startedAt':time.time()};save(self.root/'notes-maintenance.json',config)
        def new_slide(*args,**kwargs):
            note.write_text('# 课堂\n![[slide-01.png]]\n已有内容',encoding='utf-8');return []
        def complete(config,rows,bridge,root,**kwargs):
            self.assertEqual(rows,[]);self.assertIn('课堂.md',kwargs['changed'])
            save(self.root/'notes-maintenance.json',{**config,'enabled':False})
            return {'state':'finished','historyConfirmed':True},{}
        with patch('notes_maintenance.collect',side_effect=new_slide),patch('notes_maintenance.run_batch',side_effect=complete):watch(Path('bridge.mjs'),self.root)
        state=read(self.root/'notes-maintenance-state.json')
        self.assertEqual(state['completedBatches'],1);self.assertFalse(state['active'])


if __name__ == '__main__':unittest.main()
