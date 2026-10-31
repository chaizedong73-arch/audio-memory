import unittest
from unittest.mock import patch
import recorder

class DeviceSelectionTests(unittest.TestCase):
    def test_default_input_fallback(self):
        devices=[{'name':'Other microphone','max_input_channels':1,'hostapi':0}]
        def query(index=None, kind=None):
            return devices if index is None else {'max_input_channels':1,'default_samplerate':44100}
        with patch.object(recorder.sd,'query_devices',side_effect=query), patch.object(recorder.sd.default,'device',(0,-1)):
            self.assertEqual(recorder.pick_device(),(0,44100,1))

    def test_no_input_has_actionable_error(self):
        with patch.object(recorder.sd,'query_devices',return_value=[]), patch.object(recorder.sd.default,'device',(-1,-1)):
            with self.assertRaisesRegex(RuntimeError,'没有可用的默认录音设备'):
                recorder.pick_device()

if __name__=='__main__':unittest.main()
