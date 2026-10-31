import json,tempfile,unittest
from pathlib import Path
import visual_experiment
from visual_vocabulary_test import run

class ContractTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def test_missing_cases_block_without_inference(self):
  p=self.root/'visual-experiment-suite.json';p.write_text(json.dumps({'cases':[]}))
  with self.assertRaises(ValueError):visual_experiment.validate_suite(self.root,{'caseId':'complex'})
 def test_raw_non_json_is_not_lost(self):
  result,raw,nonstandard=visual_experiment.tolerant_content('图形A → 图形B\n这个箭头含义不确定。')
  self.assertTrue(nonstandard);self.assertEqual(result['text'],raw);self.assertEqual(result['words'],[])
 def test_lossless_ledger_and_failure(self):
  p=self.root/'out/visual-vocabulary/runs/one';p.mkdir(parents=True)
  ledger=visual_experiment.record(self.root,p,{'model':'test','task':'vision','caseId':'complex'},{'text':'visible A','rawAnswer':'原答\nA → B','task':'vision','warnings':[{'code':'nonstandard-format'}]})
  self.assertIn('原答\nA → B',Path(ledger).read_text(encoding='utf-8'))
  p2=p.with_name('two');p2.mkdir();visual_experiment.record(self.root,p2,{'model':'test'},{'error':'cancelled'})
  text=Path(ledger).read_text(encoding='utf-8');self.assertIn('cancelled',text);self.assertIn('原答',text)
 def test_ocr_cloud_blocked_before_network(self):
  p=self.root/'out/visual-vocabulary/inputs/input.png';p.parent.mkdir(parents=True);p.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
  with self.assertRaises(ValueError):run({'image':str(p),'width':100,'height':100,'task':'ocr','model':'doubao-seed-2-0-mini-260428'},self.root,ask=lambda b:self.fail('OCR uploaded image'))

if __name__=='__main__':unittest.main()
