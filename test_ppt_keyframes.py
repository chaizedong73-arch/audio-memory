import io,tempfile,unittest
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageEnhance
import cv2,numpy as np
from ppt_keyframes import SlideDetector

def page(number=1):
 image=Image.new('RGB',(960,600),'white');draw=ImageDraw.Draw(image)
 font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',34)
 draw.text((55,35),'SLIDE '+str(number),font=font,fill='black')
 for n in range(6):draw.text((65,120+n*60),('Database tables and relations' if number==1 else 'Neural network hidden states')+' '+str(n),font=font,fill='#243454')
 if number==2:draw.rectangle((720,100,900,460),fill='#4371ba')
 return image
def raw(image):
 f=io.BytesIO();image.save(f,'PNG');return f.getvalue()

class SlideTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.d=SlideDetector(Path(self.temp.name));self.now=0
 def tearDown(self):self.temp.cleanup()
 def feed(self,image,n=3):
  result=None
  for _ in range(n):result=self.d.feed(raw(image),self.now);self.now+=1
  return result
 def test_one_per_page_and_revisit(self):
  self.feed(page());self.feed(page(),5);self.assertEqual(len(self.d.items),1)
  self.feed(page(2));self.assertEqual(len(self.d.items),2)
  self.feed(page());self.assertEqual(len(self.d.items),2)
  self.assertEqual(self.d.current,self.d.items[0]['id'])
 def test_transition_needs_stability(self):
  self.feed(page());self.feed(page(2),1);self.feed(page(),3);self.assertEqual(len(self.d.items),1)
 def test_lighting_and_translation(self):
  self.feed(page())
  self.feed(ImageEnhance.Brightness(page()).enhance(.8));self.assertEqual(len(self.d.items),1)
  moved=cv2.warpAffine(np.array(page()),np.float32([[1,0,4],[0,1,3]]),(960,600),borderMode=cv2.BORDER_REFLECT)
  self.feed(Image.fromarray(moved));self.assertEqual(len(self.d.items),1)
 def test_roi_excludes_moving_surroundings(self):
  self.d.configure([.1,.1,.8,.8]);first=page();self.feed(first)
  changed=first.copy();ImageDraw.Draw(changed).rectangle((0,0,80,600),fill='black');self.feed(changed)
  self.assertEqual(len(self.d.items),1);self.assertEqual((self.d.items[0]['width'],self.d.items[0]['height']),(768,480))
 def test_blank_and_invalid_region(self):
  self.feed(Image.new('RGB',(960,600),'white'),5);self.assertEqual(len(self.d.items),0)
  for roi in [[0,0,0,1],[0,0,2,1],[float('nan'),0,.5,.5]]:
   with self.assertRaises(ValueError):self.d.configure(roi)
 def test_retains_source_and_index(self):
  self.feed(page());item=self.d.items[0]
  self.assertTrue(Path(item['path']).is_file());self.assertTrue((self.d.folder/'index.json').exists());self.assertEqual(item['firstSeenAt'],0)

if __name__=='__main__':unittest.main()
