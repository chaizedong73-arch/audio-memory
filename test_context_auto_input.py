import datetime as dt
import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import context_auto
from transcript_corrections import apply_manual_text

class ContextInputTests(unittest.TestCase):
    def test_all_segments_in_one_audio_file_reach_context_model(self):
        now=1793410000.0
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); day=dt.datetime.fromtimestamp(now).strftime('%Y%m%d')
            timeline=root/'out'/day/'timeline.jsonl'; timeline.parent.mkdir(parents=True)
            rows=[{'file':'same.wav','start':i,'end':i+0.5,'ts':now-20+i,'text':f'第{i}句话'} for i in range(3)]
            timeline.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows),encoding='utf-8')
            key=root/'key';key.write_text('test',encoding='utf-8');received=[]
            def invoke(prompt, _key, _model):
                self.assertEqual(_model,'glm-5.3-flash')
                received.extend(json.loads(prompt.rsplit('字幕：',1)[1]))
                return json.dumps({'sixElements':{k:{'value':'未知','sources':[]} for k in context_auto.ELEMENTS},'narrative':'测试情节','uncertainties':[]},ensure_ascii=False)
            with patch.object(context_auto,'KEY',key): self.assertEqual(context_auto.generate(root,now,invoke),'ready')
            self.assertEqual([row['text'] for row in received],['第0句话','第1句话','第2句话'])
            result=json.loads((root/'out'/'context-auto'/'candidate.json').read_text(encoding='utf-8'))
            self.assertEqual(len(result['sources']),3)
            self.assertEqual(result['candidate']['narrative'],'测试情节')
            self.assertEqual(result['model'],'glm-5.3-flash')

    def test_missing_segment_coordinates_do_not_collapse_distinct_rows(self):
        now=1793410000.0
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); day=dt.datetime.fromtimestamp(now).strftime('%Y%m%d')
            timeline=root/'out'/day/'timeline.jsonl';timeline.parent.mkdir(parents=True)
            rows=[{'file':'same.wav','ts':now-10+i,'text':f'无坐标{i}'} for i in range(2)]
            timeline.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows),encoding='utf-8')
            key=root/'key';key.write_text('test',encoding='utf-8');received=[]
            def invoke(prompt,_key,_model):
                received.extend(json.loads(prompt.rsplit('字幕：',1)[1]))
                return json.dumps({'sixElements':{k:{'value':'未知','sources':[]} for k in context_auto.ELEMENTS},'narrative':'测试','uncertainties':[]},ensure_ascii=False)
            with patch.object(context_auto,'KEY',key):self.assertEqual(context_auto.generate(root,now,invoke),'ready')
            self.assertEqual([row['text'] for row in received],['无坐标0','无坐标1'])


    def test_cloud_revision_only_replaces_matching_segment(self):
        now=1793410000.0
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); day=dt.datetime.fromtimestamp(now).strftime('%Y%m%d')
            local=root/'out'/day/'timeline.jsonl';local.parent.mkdir(parents=True)
            cloud=root/'out'/'cloud-asr-fixture'/day/'timeline.jsonl';cloud.parent.mkdir(parents=True)
            def row(start,text):return {'file':'same.wav','start':start,'end':start+0.5,'ts':now-20+start,'text':text}
            local.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in [row(0,'第一句'),row(1,'错误第二句')]),encoding='utf-8')
            cloud.write_text(json.dumps(row(1,'修正第二句'),ensure_ascii=False)+'\n',encoding='utf-8')
            key=root/'key';key.write_text('test',encoding='utf-8');received=[]
            def invoke(prompt,_key,_model):
                received.extend(json.loads(prompt.rsplit('字幕：',1)[1]))
                return json.dumps({'sixElements':{k:{'value':'未知','sources':[]} for k in context_auto.ELEMENTS},'narrative':'测试','uncertainties':[]},ensure_ascii=False)
            with patch.object(context_auto,'KEY',key):self.assertEqual(context_auto.generate(root,now,invoke),'ready')
            self.assertEqual([x['text'] for x in received],['第一句','修正第二句'])
            self.assertIn('cloud-asr-fixture',received[1]['id'])


    def test_invalid_source_does_not_replace_previous_candidate(self):
        now=1793410000.0
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);day=dt.datetime.fromtimestamp(now).strftime('%Y%m%d')
            timeline=root/'out'/day/'timeline.jsonl';timeline.parent.mkdir(parents=True)
            timeline.write_text(json.dumps({'file':'same.wav','start':0,'end':1,'ts':now-1,'text':'一条测试字幕'},ensure_ascii=False)+'\n',encoding='utf-8')
            dest=root/'out'/'context-auto';dest.mkdir();original={'candidate':{'narrative':'旧情景'}}
            (dest/'candidate.json').write_text(json.dumps(original,ensure_ascii=False),encoding='utf-8')
            key=root/'key';key.write_text('test',encoding='utf-8')
            def invoke(_prompt,_key,_model):
                six={k:{'value':'未知','sources':[]} for k in context_auto.ELEMENTS}
                six['cause']={'value':'测试','sources':['不存在的字幕']}
                return json.dumps({'sixElements':six,'narrative':'错误情景'},ensure_ascii=False)
            with patch.object(context_auto,'KEY',key):self.assertEqual(context_auto.generate(root,now,invoke),'error')
            self.assertEqual(json.loads((dest/'candidate.json').read_text(encoding='utf-8')),original)
            self.assertIn('不存在的字幕来源',json.loads((dest/'state.json').read_text(encoding='utf-8'))['message'])


    def test_last_hour_is_not_silently_truncated_to_forty_segments(self):
        now=1793410000.0
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);day=dt.datetime.fromtimestamp(now).strftime('%Y%m%d')
            timeline=root/'out'/day/'timeline.jsonl';timeline.parent.mkdir(parents=True)
            timeline.write_text(''.join(json.dumps({'file':'same.wav','start':i,'end':i+0.5,'ts':now-100+i,'text':f'段落{i}'},ensure_ascii=False)+'\n' for i in range(45)),encoding='utf-8')
            key=root/'key';key.write_text('test',encoding='utf-8');received=[]
            def invoke(prompt,_key,_model):
                received.extend(json.loads(prompt.rsplit('字幕：',1)[1]))
                return json.dumps({'sixElements':{k:{'value':'未知','sources':[]} for k in context_auto.ELEMENTS},'narrative':'测试'},ensure_ascii=False)
            with patch.object(context_auto,'KEY',key):self.assertEqual(context_auto.generate(root,now,invoke),'ready')
            self.assertEqual(len(received),45)
            self.assertEqual(received[0]['text'],'段落0')


    def test_last_hour_includes_previous_day_around_midnight(self):
        now=dt.datetime(2026,10,31,0,10).timestamp()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for day,ts,text in [('20261030',now-1200,'前一天'),('20261031',now-30,'当天')]:
                timeline=root/'out'/day/'timeline.jsonl';timeline.parent.mkdir(parents=True)
                timeline.write_text(json.dumps({'ts':ts,'text':text},ensure_ascii=False)+'\n',encoding='utf-8')
            key=root/'key';key.write_text('test',encoding='utf-8');received=[]
            def invoke(prompt,_key,_model):
                received.extend(json.loads(prompt.rsplit('字幕：',1)[1]))
                return json.dumps({'sixElements':{k:{'value':'未知','sources':[]} for k in context_auto.ELEMENTS},'narrative':'测试'},ensure_ascii=False)
            with patch.object(context_auto,'KEY',key):self.assertEqual(context_auto.generate(root,now,invoke),'ready')
            self.assertEqual([row['text'] for row in received],['前一天','当天'])


    def test_non_unknown_element_requires_valid_source(self):
        six={k:{'value':'未知','sources':[]} for k in context_auto.ELEMENTS}
        six['cause']={'value':'发生了一件事','sources':[]}
        with self.assertRaisesRegex(ValueError,'缺少字幕来源'):
            context_auto.validate_candidate({'sixElements':six,'narrative':'情节'},[{'id':'line:1'}])


    def test_context_uses_user_corrected_text_and_preserves_original(self):
        now=1793410000.0
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);day=dt.datetime.fromtimestamp(now).strftime('%Y%m%d');timeline=root/'out'/day/'timeline.jsonl';timeline.parent.mkdir(parents=True)
            row={'file':'same.wav','start':0,'end':1,'ts':now-1,'text':'这是试图'}
            timeline.write_text(json.dumps(row,ensure_ascii=False)+'\n',encoding='utf-8');original=timeline.read_bytes()
            version=hashlib.sha256(json.dumps(row,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            apply_manual_text(root,timeline,1,version,'这是视图')
            key=root/'key';key.write_text('test',encoding='utf-8');received=[]
            def invoke(prompt,_key,_model):
                received.extend(json.loads(prompt.rsplit('字幕：',1)[1]))
                return json.dumps({'sixElements':{k:{'value':'未知','sources':[]} for k in context_auto.ELEMENTS},'narrative':'测试'},ensure_ascii=False)
            with patch.object(context_auto,'KEY',key):self.assertEqual(context_auto.generate(root,now,invoke),'ready')
            self.assertEqual(received[0]['text'],'这是视图');self.assertEqual(timeline.read_bytes(),original)

if __name__=='__main__':unittest.main()
