import unittest
from visual_benchmark import score,contains
class BenchmarkTests(unittest.TestCase):
 def test_original_word_boundaries_survive_layout_normalization(self):
  for word in ('What','time','is','it'):
   self.assertTrue(contains('What time is it ?',word))
  self.assertTrue(contains('GAN (2014)','GAN(2014)'))
  self.assertFalse(contains('this','is'))
 def test_literal_not_semantic(self):
  gold={'version':'test','anchors':[{'text':'Geoffery Hinton'},{'text':'GAN(2014)'},{'text':'RNN'},{'text':'ResNet'}]}
  r=score({'text':'Geoffrey Hinton\nGAN (2014)\nRNN\nresnet'},gold)
  self.assertEqual([a['status'] for a in r['rows']],['missing','exact','exact','case-difference'])
 def test_no_subword_or_cross_field_match(self):
  self.assertFalse(contains('PGGAN','GAN'))
  r=score({'words':[{'text':'Alpha'},{'text':'Go'}]},{'version':'x','anchors':[{'text':'AlphaGo'}]})
  self.assertEqual(r['exactHits'],0)
if __name__=='__main__':unittest.main()
