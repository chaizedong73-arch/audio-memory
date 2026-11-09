import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from cloud_usage import record_usage, UsageRecordingError
from cloud_transcriber import transcribe


class UsageTests(unittest.TestCase):
    def test_official_estimate_and_unknown_custom_price(self):
        with tempfile.TemporaryDirectory() as folder:
            args=dict(file='audio.wav',model='doubao-seed-2-0-mini-260428',protocol='ark_audio',duration=30,
                      result={'usage':{'prompt_tokens':1000,'completion_tokens':100}})
            known=record_usage(folder,**args,official=True)
            self.assertEqual(known['estimatedYuan'],0.0064)
            self.assertEqual(record_usage(folder,**args)['estimatedYuan'],None)
            self.assertEqual(len(next(Path(folder).rglob('*.jsonl')).read_text().splitlines()),2)

    def test_missing_usage_error_and_bad_tokens_are_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            for result in [None,{'usage':{'prompt_tokens':-1,'completion_tokens':1}},
                           {'usage':{'prompt_tokens':True,'completion_tokens':1}}]:
                row=record_usage(folder,file='a.wav',model='doubao-seed-2-0-mini-260428',protocol='ark_audio',
                                 duration=1,result=result,official=True)
                self.assertIsNone(row['estimatedYuan'])
            row=record_usage(folder,file='a.wav',model='custom',protocol='ark_audio',duration=1,error=TimeoutError())
            self.assertEqual(row['status'],'error')
            self.assertEqual(row['errorType'],'TimeoutError')

    def test_empty_and_truncated_responses_are_recorded(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);audio=root/'20261106_010000_0001.wav'
            with wave.open(str(audio),'wb') as stream:
                stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(16000);stream.writeframes(b'\x01\x00'*16000)
            transcribe(audio,root,root/'unused',send=lambda _: {'choices':[{'message':{'content':''}}],'usage':{'prompt_tokens':7,'completion_tokens':0}})
            with self.assertRaises(ValueError):
                transcribe(audio,root,root/'unused',send=lambda _: {'choices':[{'finish_reason':'length','message':{'content':'cut'}}]})
            rows=[json.loads(x) for x in next((root/'out/cloud-usage').glob('*.jsonl')).read_text().splitlines()]
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[0]['inputTokens'],7)
            self.assertNotIn('text',rows[0])

    def test_ledger_write_failure_is_distinct_from_request_failure(self):
        with patch('pathlib.Path.open',side_effect=OSError('full')):
            with self.assertRaises(UsageRecordingError):
                record_usage(Path(tempfile.gettempdir())/'audio-cost-fixture',file='a',model='custom',protocol='ark_audio',duration=1)


if __name__=='__main__':unittest.main()
