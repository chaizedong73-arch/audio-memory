import datetime as dt
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import cloud_asr_trial as cloud


class AudioModeTests(unittest.TestCase):
    def test_permission_requires_current_unexpired_cloud_generation(self):
        settings = {'mode': 'cloud', 'generation': 'one', 'deadline': 100}
        self.assertTrue(cloud.permitted(settings, 'one', 99))
        self.assertFalse(cloud.permitted(settings, 'one', 100))
        self.assertFalse(cloud.permitted(settings, 'two', 99))
        self.assertFalse(cloud.permitted({**settings, 'mode': 'local'}, 'one', 99))

    def test_switch_to_local_prevents_next_cloud_request(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'record').mkdir()
            started = time.time()-10
            settings = {'mode': 'cloud', 'generation': 'test', 'deadline': time.time()+30,
                        'startedAt': started, 'budgetYuan': 5}
            (root/'transcription-control.json').write_text(json.dumps(settings))
            for i in range(2):
                name = dt.datetime.now().strftime('%Y%m%d_%H%M%S')+f'_{i:04d}.wav'
                (root/'record'/name).write_bytes(b'fixture')
            calls = []
            def request(body, timeout):
                calls.append(body)
                (root/'transcription-control.json').write_text(json.dumps({**settings, 'mode': 'local'}))
                return {'choices': [{'message': {'content': '课堂示例'}, 'finish_reason': 'stop'}],
                        'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
            with patch.object(cloud, 'HERE', root), patch.object(cloud, 'STATUS', root/'cloud-asr-trial.json'), \
                    patch.object(cloud, 'payload', return_value=(15, {})), patch.object(cloud, 'request', side_effect=request), \
                    patch('classroom_materials.publish'):
                cloud.trial(controlled=True)
            state = json.loads((root/'cloud-asr-trial.json').read_text(encoding='utf-8'))
            self.assertEqual(len(calls), 1)
            self.assertEqual(state['stopReason'], 'user_switch')
            self.assertFalse(state['active'])
            self.assertEqual(len(state['completed']), 1)


if __name__ == '__main__': unittest.main()
