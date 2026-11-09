import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import prepare_visual_models as m

class RetirementTests(unittest.TestCase):
 def test_prepare_never_fetches_retired_weights(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Path(tmp);manifest=store/'catalog.json'
   retired=['local-vlm:qwen3vl2b','local-vlm:qwen3vl4b','local-vlm:glmocr','local:ppocr-v6-tiny']
   manifest.write_text(json.dumps({'retiredIds':retired}),encoding='utf-8')
   fetched=[]
   def metadata(url):
    self.assertIn('api.github.com',url)
    return [{'assets':[{'name':'test-bin-win-cpu-x64.zip','browser_download_url':'https://example.invalid/runtime'}]}]
   def fetch(row):
    fetched.append(row['path']);return {'path':row['path'],'bytes':0,'sha256':'fixture'}
   defaults={}
   for version,size,lang in [('PP-OCRv4','mobile','ch'),('PP-OCRv4','server','ch'),('PP-OCRv4','server','ch_doc'),('PP-OCRv5','mobile','ch'),('PP-OCRv5','server','ch'),('PP-OCRv6','tiny','multi'),('PP-OCRv6','small','multi'),('PP-OCRv6','medium','multi')]:
    group=defaults.setdefault(version,{'det':{},'rec':{}})
    for task,key in [('det',f'{"multi" if version=="PP-OCRv6" else "ch"}_{version}_det_{size}'),('rec',f'{lang}_{version}_rec_{size}')]:
     group[task][key]={'model_dir':'https://example.invalid/'+key,'SHA256':'fixture'}
   with patch.object(m,'STORE',store),patch.object(m,'MANIFEST',manifest),patch.object(m,'get',metadata),patch.object(m,'fetch',fetch),patch.object(m,'load_defaults',return_value=defaults):m.prepare()
   saved=json.loads(manifest.read_text(encoding='utf-8'))
   self.assertFalse(set(retired)&{x['id'] for x in saved['catalog']})
   self.assertTrue(any('small' in p for p in fetched))
   self.assertFalse(any('tiny' in p or 'qwen3vl' in p or 'glmocr' in p for p in fetched))
   self.assertEqual(saved['retiredIds'],sorted(retired))

if __name__=='__main__':unittest.main()
