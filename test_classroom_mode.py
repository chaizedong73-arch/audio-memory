import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from classroom_mode import enabled,set_enabled,snapshot_images
from subtitle_maintenance import references
from ppt_concepts import index_images
from notes_maintenance import run_batch
from visual_vocabulary_test import run

class ClassroomTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def test_off_keeps_standing_settings_but_stops_notes(self):
  for name in ('subtitle-maintenance.json','notes-maintenance.json'):
   (self.root/name).write_text(json.dumps({'enabled':True}),encoding='utf-8')
  (self.root/'transcription-control.json').write_text('{"mode":"local"}',encoding='utf-8')
  set_enabled(self.root,True);self.assertTrue(enabled(self.root))
  set_enabled(self.root,False);self.assertFalse(enabled(self.root))
  self.assertTrue(json.loads((self.root/'subtitle-maintenance.json').read_text())['enabled'])
  self.assertFalse(json.loads((self.root/'notes-maintenance.json').read_text())['enabled'])
  self.assertEqual(json.loads((self.root/'transcription-control.json').read_text())['mode'],'local')
 def test_off_does_not_read_course_or_call_models(self):
  with patch.object(Path,'rglob',side_effect=AssertionError('read external notes')):
   self.assertEqual(references({},'caption',self.root),([],[]))
  with self.assertRaisesRegex(ValueError,'上课模式'):index_images([],self.root)
  with self.assertRaisesRegex(ValueError,'上课模式'):run({},self.root,ask=lambda b:self.fail('cloud call'))
  with self.assertRaisesRegex(ValueError,'上课模式'):run_batch({},[],Path('fixture'),self.root,runner=lambda *a,**k:self.fail('dispatch'))
 def test_enabled_snapshots_are_local_and_content_bound(self):
  set_enabled(self.root,True)
  source=self.root/'original.png';source.write_bytes(b'picture')
  first=snapshot_images([{'path':str(source)}],self.root)[0]
  self.assertTrue(Path(first['path']).is_relative_to(self.root/'classroom/materials'))
  self.assertEqual(Path(first['path']).read_bytes(),b'picture')
  source.write_bytes(b'updated')
  second=snapshot_images([{'path':str(source)}],self.root)[0]
  self.assertNotEqual(first['path'],second['path'])
  self.assertEqual(source.read_bytes(),b'updated')

if __name__=='__main__':unittest.main()
