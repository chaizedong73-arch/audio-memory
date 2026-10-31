from classroom_mode import set_enabled
import json,tempfile,time,unittest
from pathlib import Path
from ppt_concepts import index_images,terms
from subtitle_maintenance import review,conflicting_symbols
from subtitle_decisions import decide
from notes_maintenance import collect,save
from transcript_corrections import record_key,load
class ConceptTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);set_enabled(self.root,True);self.notes=self.root/'notes';self.notes.mkdir();self.doc=self.notes/'课件.md';self.doc.write_text('PPT出现ht-1。',encoding='utf-8');self.source=self.root/'out'/time.strftime('%Y%m%d')/'timeline.jsonl';self.source.parent.mkdir(parents=True);self.row={'file':'one','text':'这里是hz.1，不是hz.10','start':0,'end':2,'ts':time.time()};self.source.write_text(json.dumps(self.row)+'\n',encoding='utf-8');self.group=collect(self.root,0,{})[0];self.config={'notesRoot':str(self.notes),'lesson':'课件'}
 def tearDown(self):self.tmp.cleanup()
 def ask(self,body):
  self.assertFalse(any(c.get('type')=='image_url' for c in body['messages'][0]['content']))
  key=record_key(self.source,self.row)
  answer={'status':'needs_confirmation','reason':'多种写法冲突，资料候选ht-1','evidence':['ref1'],'context':'符号核对','parts':[{'id':key,'text':self.row['text']}],'confirmation':{'term':'ht-1','variants':['hz.1'],'question':'课件候选是ht-1，是否使用？'}}
  return {'choices':[{'message':{'content':json.dumps(answer)}}],'usage':{}}
 def pending(self):
  receipt,_,_=review(self.group,self.config,'',self.root,self.ask);save(self.root/'subtitle-reviews.json',{'items':{'one':receipt}});return receipt
 def test_local_cache_once_and_image_change_invalidation(self):
  img=self.notes/'slide.png';img.write_bytes(b'one');calls=[]
  def ocr(paths):calls.append(paths);return [{'path':str(p),'text':'ht-1 RNN ε','words':[]} for p in paths]
  images=[{'path':str(img)}];first=index_images(images,self.root,ocr);second=index_images(images,self.root,ocr);self.assertEqual(len(calls),1);self.assertEqual(first[0]['hash'],second[0]['hash']);img.write_bytes(b'two');third=index_images(images,self.root,ocr);self.assertEqual(len(calls),2);self.assertNotEqual(first[0]['hash'],third[0]['hash']);self.assertIn('ht-1',terms('ht-1 ht.1'))
 def test_confirm_edit_and_note_gate(self):
  receipt=self.pending();self.assertFalse(load(self.root)['records']);self.assertEqual(collect(self.root,0,{},require_review=True),[])
  decide(self.root,receipt['id'],'accept','ht.1');row=collect(self.root,0,{},require_review=True)[0];self.assertEqual(row['text'],'这里是ht.1，不是hz.10');self.assertEqual(self.doc.read_text(encoding='utf-8'),'PPT出现ht-1。');self.assertEqual(json.loads((self.root/'subtitle-terms.json').read_text(encoding='utf-8'))['items'][0]['term'],'ht.1')
 def test_reject_preserves_original_and_stops_reprompt(self):
  receipt=self.pending();decide(self.root,receipt['id'],'reject');self.assertFalse(load(self.root)['records']);self.assertEqual(json.loads((self.root/'subtitle-reviews.json').read_text(encoding='utf-8'))['items']['one']['status'],'rejected')
 def test_changed_version_rejects_old_decision(self):
  receipt=self.pending();self.row['text']='new';self.source.write_text(json.dumps(self.row)+'\n',encoding='utf-8')
  with self.assertRaises(ValueError):decide(self.root,receipt['id'],'accept','ht-1')
  self.assertFalse(load(self.root)['records'])
 def test_conflicting_spellings_are_not_identity(self):
  self.assertTrue(conflicting_symbols('ht.1 hz.1 ht-1 he.1'));self.assertFalse(conflicting_symbols('ht.1 ht.1 ht.1 ht-1'))
if __name__=='__main__':unittest.main()
