from classroom_mode import set_enabled
import json,tempfile,unittest
from pathlib import Path
from visual_vocabulary_test import run
import visual_lab

class LabTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);set_enabled(self.root,True)
  self.image=self.root/'out/visual-vocabulary/inputs/input.png';self.image.parent.mkdir(parents=True);self.image.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
  self.job={'image':str(self.image),'width':100,'height':100,'model':'fake-vlm','task':'vision'}
 def tearDown(self):self.tmp.cleanup()
 def response(self,body):
  return {'choices':[{'message':{'content':json.dumps({'text':'diagram','words':[{'text':'network','bbox':None}],'elements':[{'id':'a'},{'id':'b'}],'relations':[{'source':'a','target':'b','inferred':False}]})}}]}
 def test_vision_and_ocr_cache_separate(self):
  a=run(self.job,self.root,ask=self.response);self.assertEqual(len(a['visualRelations']),1)
  sent=[]
  with self.assertRaises(ValueError):run(dict(self.job,task='ocr'),self.root,ask=lambda b:(sent.append(b) or self.response(b)))
  self.assertEqual(len(sent),0)
 def test_ocr_cannot_act_as_visual_model(self):
  with self.assertRaises(ValueError):run(dict(self.job,model='local:windows'),self.root)
 def test_dangling_relation_rejected(self):
  def bad(b):
   v=self.response(b);s=json.loads(v['choices'][0]['message']['content']);s['relations'][0]['target']='missing';v['choices'][0]['message']['content']=json.dumps(s);return v
  with self.assertRaises(ValueError):run(self.job,self.root,ask=bad)
 def test_local_endpoint_cannot_be_remote(self):
  (self.root/'visual-lab-providers.json').write_text(json.dumps([{'id':'x','local':True,'baseUrl':'https://example.com','model':'x'}]))
  with self.assertRaises(ValueError):visual_lab.request('custom:x',{},self.root)

if __name__=='__main__':unittest.main()
