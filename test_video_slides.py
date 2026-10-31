import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from test_ppt_keyframes import page
from video_slides import extract


class VideoSlideTests(unittest.TestCase):
    def test_real_decode_revisit_and_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root/'slides.avi'
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 5, (960,600))
            self.assertTrue(writer.isOpened())
            for number in (1, 2, 1):
                frame = cv2.cvtColor(np.array(page(number)), cv2.COLOR_RGB2BGR)
                for _ in range(25):
                    writer.write(frame)
            writer.release()
            result = extract(video, root)
            self.assertEqual(result['uniquePages'], 2)
            self.assertEqual(len(result['occurrences']), 3)
            self.assertEqual(result['occurrences'][0]['pageId'], result['occurrences'][2]['pageId'])
            self.assertEqual(result['occurrences'][-1]['endSeconds'], 15)
            self.assertEqual([x['startSeconds'] for x in result['occurrences']], [0,5,10])
            self.assertTrue((Path(result['index']).parent/'contact-001.jpg').exists())
            self.assertEqual(len(json.loads(Path(result['index']).read_text(encoding='utf-8'))['items']), 2)


if __name__ == '__main__':
    unittest.main()
