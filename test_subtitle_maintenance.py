from classroom_mode import set_enabled
import json,tempfile,time,unittest
from pathlib import Path
from subtitle_maintenance import review,digest
from notes_maintenance import collect
from transcript_corrections import load,record_key
class SubtitleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);set_enabled(self.root,True);self.notes=self.root/'notes';self.notes.mkdir();self.doc=self.notes/'RNN.md';self.doc.write_text('RNN：循环神经网络。ε：埃普西隆。',encoding='utf-8')
  self.source=self.root/'out'/time.strftime('%Y%m%d')/'timeline.jsonl';self.source.parent.mkdir(parents=True);self.row={'file':'one','text':'讲阿恩恩','start':1,'end':2,'ts':time.time(),'t':'12:00:00'};self.source.write_text(json.dumps(self.row)+'\n',encoding='utf-8')
  self.config={'notesRoot':str(self.notes),'lesson':'RNN'};self.group=collect(self.root,0,{})[0]
 def tearDown(self):self.tmp.cleanup()
 def answer(self,status='screened',evidence=None):
  def ask(body):
   self.assertNotIn('tools',body);self.assertIn('RNN',str(body));key=record_key(self.source,self.row)
   return {'choices':[{'message':{'content':json.dumps({'status':status,'reason':'资料中有RNN，音近但仍须复核','evidence':evidence if evidence is not None else [str(self.doc.resolve())],'context':'讲循环网络','parts':[{'id':key,'text':'讲RNN'}]})}}],'usage':{}}
  return ask
 def test_overlay_only_and_note_gate_invalidates_on_change(self):
  original=self.doc.read_bytes();receipt,_,_=review(self.group,self.config,'',self.root,self.answer());self.assertEqual(self.doc.read_bytes(),original)
  self.assertEqual(load(self.root)['records'][record_key(self.source,self.row)]['id'],record_key(self.source,self.row))
  self.assertEqual(collect(self.root,0,{},require_review=True),[])
  (self.root/'subtitle-reviews.json').write_text(json.dumps({'items':{'one':receipt}}),encoding='utf-8');self.assertEqual(collect(self.root,0,{},require_review=True)[0]['text'],'讲RNN')
  self.row['text']='改变原文';self.source.write_text(json.dumps(self.row)+'\n',encoding='utf-8');self.assertEqual(collect(self.root,0,{},require_review=True),[])
 def test_uncertain_cannot_write_overlay(self):
  result,_,_=review(self.group,self.config,'',self.root,self.answer('uncertain'));self.assertEqual(result['status'],'uncertain');self.assertFalse((self.root/'transcript-corrections.json').exists())
 def test_fabricated_evidence_rejected(self):
  with self.assertRaises(ValueError):review(self.group,self.config,'',self.root,self.answer(evidence=['invented']))
  self.assertFalse((self.root/'transcript-corrections.json').exists())
 def test_human_annotation_protected_without_model_call(self):
  key=record_key(self.source,self.row);(self.root/'transcript-corrections.json').write_text(json.dumps({'records':{},'annotations':[{'recordId':key}]}))
  result,_,_=review(self.group,self.config,'',self.root,lambda x:self.fail('human override called model'));self.assertEqual(result['status'],'uncertain')
 def test_stopped_and_expired_loops_return_to_idle_without_request(self):
  from subtitle_maintenance import watch
  for enabled in (False,True):
   (self.root/'subtitle-maintenance.json').write_text(json.dumps({'enabled':enabled,'startedAt':time.time()-10,'deadline':time.time()-1}),encoding='utf-8')
   (self.root/'notes-maintenance.json').write_text(json.dumps(self.config),encoding='utf-8')
   watch(self.root)
   state=json.loads((self.root/'subtitle-maintenance-state.json').read_text(encoding='utf-8'))
   self.assertFalse(state['active']);self.assertFalse(json.loads((self.root/'subtitle-maintenance.json').read_text())['enabled'])
if __name__=='__main__':unittest.main()
