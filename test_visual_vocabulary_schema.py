import unittest
from visual_vocabulary_schema import build_structure

class SchemaTests(unittest.TestCase):
 def build(self, words):return build_structure(words,'fixture','local:windows',1440,1080)
 def word(self,text,x,y=10,w=20,h=20):return dict(text=text,bbox=[x,y,w,h],uncertain=False)
 def test_chinese_and_evidence(self):
  words=[self.word('序',10),self.word('列',32),self.word('RNN',60)]
  r=self.build(words)
  self.assertEqual(r['groups'][0]['text'],'序列RNN')
  self.assertEqual(len(r['observations']),3)
  self.assertEqual(r['groups'][0]['observationIds'],['o00000','o00001','o00002'])
  self.assertEqual(r['concepts'],[])
  self.assertNotIn('id',words[0])
 def test_columns_and_rows_are_not_merged(self):
  r=self.build([self.word('left',10),self.word('right',600),self.word('next',10,80)])
  self.assertEqual(len(r['groups']),3)
 def test_unknown_location_and_variants_preserved(self):
  r=self.build([dict(text='ht-l',bbox=None),self.word('ht-1',10)])
  self.assertEqual({g['text'] for g in r['groups']},{'ht-l','ht-1'})
  self.assertTrue(all(g['verification']=='unverified' for g in r['groups']))
 def test_duplicate_occurrences_remain_distinct(self):
  r=self.build([self.word('RNN',10),self.word('RNN',10,80)])
  self.assertNotEqual(r['groups'][0]['id'],r['groups'][1]['id'])
 def test_cloud_boxes_do_not_force_line_merges(self):
  r=build_structure([self.word('first',10),self.word('second',32)],'fixture','cloud',1440,1080)
  self.assertEqual([g['text'] for g in r['groups']],['first','second'])

if __name__=='__main__':unittest.main()
