from classroom_mode import set_enabled
import json,tempfile,unittest
from pathlib import Path
from visual_vocabulary_test import run,normalize_words
class VisualTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);set_enabled(self.root,True);self.image=self.root/'out/visual-vocabulary/inputs/a/input.png';self.image.parent.mkdir(parents=True);self.image.write_bytes(b'\x89PNG\r\n\x1a\nfixture');self.job={'image':str(self.image),'width':100,'height':100,'model':'local:windows'}
 def tearDown(self):self.tmp.cleanup()
 def ocr(self,images,root):return [{'text':'ht-1','words':[{'text':'ht-1','x':10,'y':10,'width':30,'height':10}]}]
 def test_local_without_cloud_and_preserve_glyph(self):
  result=run(self.job,self.root,ask=lambda x:self.fail('local uploaded image'),ocr_index=self.ocr);self.assertEqual(result['words'][0]['text'],'ht-1');self.assertEqual(result['words'][0]['bbox'],[100,100,300,100]);self.assertEqual(result['verification'],'unverified')
 def test_per_model_cache_and_force_rerun(self):
  run(self.job,self.root,ocr_index=self.ocr);result=run(self.job,self.root,ocr_index=lambda *args:self.fail('cache missed'));self.assertTrue(result['cached']);result=run({**self.job,'cache':False},self.root,ocr_index=self.ocr);self.assertFalse(result['cached'])
 def test_cloud_uses_selected_model_only(self):
  sent=[]
  def ask(body):
   sent.append(body);return {'choices':[{'message':{'content':json.dumps({'text':'ht.1','words':[{'text':'ht.1','kind':'符号','bbox':None,'uncertain':True}]})}}],'usage':{'prompt_tokens':100}}
  result=run({**self.job,'model':'doubao-seed-2-0-mini-260428','task':'vision'},self.root,ask=ask);self.assertEqual(sent[0]['model'],'doubao-seed-2-0-mini-260428');self.assertNotIn('tools',sent[0]);self.assertEqual(result['words'][0]['text'],'ht.1');self.assertTrue(result['words'][0]['uncertain'])
 def test_bad_coordinates_and_truncated_results_rejected(self):
  with self.assertRaises(ValueError):normalize_words([{'text':'word','bbox':[900,0,300,100]}])
  def ask(body):return {'choices':[{'finish_reason':'length','message':{'content':'partial answer'}}]}
  result=run({**self.job,'model':'test-model','task':'vision'},self.root,ask=ask)
  self.assertEqual(result['rawAnswer'],'partial answer')
  self.assertTrue(any(w['code']=='truncated' for w in result['warnings']))
 def test_paths_and_model_id_are_bounded(self):
  outside=self.root/'outside.png';outside.write_bytes(self.image.read_bytes())
  with self.assertRaises(ValueError):run({**self.job,'image':str(outside)},self.root)
  with self.assertRaises(ValueError):run({**self.job,'model':'bad model'},self.root)
 def test_bad_cloud_location_preserves_text_and_raw_evidence(self):
  def ask(body):return {'choices':[{'message':{'content':json.dumps({'text':'epsilon','words':[{'text':'epsilon','bbox':[900,0,300,100]}]})}}]}
  r=run({**self.job,'model':'test-model','task':'vision'},self.root,ask=ask)
  self.assertIsNone(r['words'][0]['bbox'])
  self.assertEqual(r['rawExtraction']['words'][0]['bbox'],[900,0,300,100])
  self.assertEqual(r['warnings'][0]['code'],'invalid-bbox')
if __name__=='__main__':unittest.main()
