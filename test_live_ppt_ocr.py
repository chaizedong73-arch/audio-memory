import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from scene_capture import Capture

class LivePptTests(unittest.TestCase):
 def test_page_triggers_ocr_without_video(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);capture=Capture(root);capture.region_mode='full'
   image=root/'page.png';image.write_bytes(b'fixture')
   data=io.BytesIO();Image.new('RGB',(30,30),'white').save(data,format='PNG')
   with patch.object(capture.slides,'feed',return_value={'path':str(image)}),patch.object(capture.slides,'persist'),patch('ocr_unit.run',return_value={'errors':[]}) as ocr,patch('visual_worker.publish'):
    capture.image(data.getvalue())
    for _ in range(100):
     if capture.ocr_completed:break
     time.sleep(.05)
    self.assertEqual(capture.ocr_completed,1);ocr.assert_called_once();self.assertFalse((root/'record'/'camera').exists())
    with self.assertRaises(ValueError):capture.command('record')
   capture.ocr_queue.put(None);capture.ocr_thread.join(timeout=3);capture.locator.close()

if __name__=='__main__':unittest.main()
