import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import classroom_mode
import scene_capture


class CameraLifecycleTests(unittest.TestCase):
    def test_managed_service_stops_and_clears_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); classroom_mode.set_enabled(root,True)
            ready=root/'ready'; stop=root/'stop'; errors=[]
            def run():
                try: scene_capture.serve(root,stop,ready)
                except Exception as error: errors.append(error)
            with patch.object(scene_capture,'PORT',0):
                thread=threading.Thread(target=run);thread.start()
                try:
                    for _ in range(100):
                        if ready.exists() or errors: break
                        time.sleep(.05)
                    self.assertTrue(ready.exists(),errors)
                    stop.write_text('stop',encoding='ascii');thread.join(timeout=6)
                    self.assertFalse(thread.is_alive())
                    self.assertFalse(ready.exists())
                    self.assertFalse((root/'out'/'scene'/'runtime.json').exists())
                    self.assertFalse(errors)
                finally:
                    stop.touch();thread.join(timeout=10)

    def test_requires_classroom_mode_before_start(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError): scene_capture.serve(Path(folder))


if __name__=='__main__': unittest.main()
