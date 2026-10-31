import contextlib
import io
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch
import numpy as np
import recorder


class RecoveryTests(unittest.TestCase):
    def test_callback_stall_reopens_instead_of_waiting_forever(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            stream = contextlib.nullcontext()
            with patch.object(sys, 'argv', ['recorder', '--device', '14', '--seconds', '1', '--out', directory]), \
                 patch.object(recorder, 'acquire_single_instance', return_value=object()), \
                 patch.object(recorder.sd, 'InputStream', return_value=stream), \
                 patch.object(recorder.time, 'sleep', side_effect=[None, KeyboardInterrupt]), \
                 contextlib.redirect_stdout(output):
                recorder.main()
            self.assertIn('Audio callback stopped', output.getvalue())

    def test_realtek_fallback_uses_wasapi(self):
        devices = [{'name': 'Realtek Mic', 'max_input_channels': 2, 'hostapi': 0}]
        with patch.object(recorder.sd, 'query_devices', return_value=devices), \
             patch.object(recorder.sd, 'query_hostapis', return_value={'name': 'Windows WASAPI'}):
            self.assertEqual(recorder.pick_device(), (0, 48000, 1))

    def test_wav_is_complete_and_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = directory + '/test.wav'
            recorder.write_wav(path, np.zeros(48000, dtype=np.float32), 48000)
            with wave.open(path) as audio:
                self.assertEqual(audio.getnframes(), 48000)
                self.assertEqual(audio.getframerate(), 48000)


if __name__ == '__main__':
    unittest.main()
