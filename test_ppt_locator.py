import io,tempfile,time,threading,unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from ppt_locator import proposals,overlap,text_evidence,AutoPptLocator

def scene():
 image=Image.new('RGB',(1280,800),(80,84,90));draw=ImageDraw.Draw(image)
 draw.rectangle((180,120,1100,640),fill='white',outline='black',width=5)
 font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',34)
 for i,line in enumerate(['Lecture 3: Neural Networks','Hidden state and input sequence','h(t) = f(h(t-1), x(t))','Read the evidence before writing notes']):draw.text((220,160+i*95),line,font=font,fill='black')
 return image
def raw(image):
 stream=io.BytesIO();image.save(stream,'PNG');return stream.getvalue()
GOOD=[{'text':'Lecture three neural networks','score':.98},{'text':'Hidden state and input sequence','score':.97}]

class LocatorTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
 def tearDown(self):self.temp.cleanup()
 def wait(self,locator):
  limit=time.monotonic()+5
  while locator.busy and time.monotonic()<limit:time.sleep(.01)
  self.assertFalse(locator.busy)
 def test_brightness_rectangle_proposal(self):
  choices=proposals(scene());self.assertTrue(choices)
  expected=[180/1280,120/800,920/1280,520/800]
  self.assertGreater(overlap(choices[0]['roi'],expected),.90)
  self.assertEqual(proposals(Image.new('RGB',(1280,800),(180,180,180))),[])
 def test_text_is_required(self):
  self.assertFalse(text_evidence([])['accepted'])
  self.assertFalse(text_evidence([{'text':'12','score':.99}])['accepted'])
  self.assertFalse(text_evidence([{'text':'This is a long low confidence line','score':.2}]*3)['accepted'])
  self.assertTrue(text_evidence(GOOD)['accepted'])
 def test_stability_lock_and_no_repeated_ocr(self):
  results=[];locator=AutoPptLocator(self.root,results.append,ocr=lambda _:GOOD)
  data=raw(scene());locator.feed(data,0);self.assertEqual(locator.ocr_calls,0)
  locator.feed(data,3);self.wait(locator);self.assertEqual(len(results),1);self.assertIsNotNone(results[0])
  for at in range(6,40,3):locator.feed(data,at)
  self.assertEqual(locator.ocr_calls,1)
 def test_negative_result_cached(self):
  results=[];locator=AutoPptLocator(self.root,results.append,ocr=lambda _:[]);data=raw(scene())
  locator.feed(data,0);locator.feed(data,3);self.wait(locator);calls=locator.ocr_calls
  locator.feed(data,15);self.wait(locator);self.assertEqual(locator.ocr_calls,calls);self.assertEqual(results,[])
 def test_manual_override_cancels_old_callback(self):
  results=[];release=threading.Event()
  def slow(_):release.wait(3);return GOOD
  locator=AutoPptLocator(self.root,results.append,ocr=slow);data=raw(scene());locator.feed(data,0);locator.feed(data,3)
  locator.reset();release.set();self.wait(locator);self.assertEqual(results,[])
 def test_lost_region_returns_to_search(self):
  results=[];locator=AutoPptLocator(self.root,results.append,ocr=lambda _:GOOD);data=raw(scene())
  locator.feed(data,0);locator.feed(data,3);self.wait(locator)
  blank=raw(Image.new('RGB',(1280,800),'#555555'))
  for at in (6,9,12):locator.feed(blank,at)
  self.assertIsNone(locator.locked);self.assertIsNone(results[-1])
 def test_capture_waits_for_auto_region_then_extracts(self):
  from scene_capture import Capture
  with patch('ppt_locator.LocalSmallOcr',return_value=lambda _:GOOD):capture=Capture(self.root)
  data=raw(scene())
  with patch('scene_capture.time.time',return_value=0):capture.image(data)
  self.assertEqual(capture.slides.items,[])
  with patch('scene_capture.time.time',return_value=3):capture.image(data)
  self.wait(capture.locator);self.assertIsNotNone(capture.slides.roi)
  for at in (100,101,102):
   with patch('scene_capture.time.time',return_value=at):capture.image(data)
  self.assertEqual(len(capture.slides.items),1);self.assertEqual(capture.locator.ocr_calls,1)
  capture.locator.close()

if __name__=='__main__':unittest.main()
