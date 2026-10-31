import json,tempfile,unittest,wave
import os
from pathlib import Path
from unittest.mock import patch
from cloud_transcriber import transcribe

class CloudTranscriberTests(unittest.TestCase):
 def test_audio_result_is_written_as_timestamped_subtitle(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);file=root/'20261101_120000_0001.wav'
   with wave.open(str(file),'wb') as audio:
    audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(b'\x01\x00'*16000)
   calls=[]
   row=transcribe(file,root,root/'unused',send=lambda body:calls.append(body) or {'choices':[{'message':{'content':'测试文字'}}]})
   self.assertEqual(row['text'],'测试文字');self.assertEqual(len(calls),1)
   saved=json.loads(next((root/'out').rglob('timeline.jsonl')).read_text(encoding='utf-8'))
   self.assertEqual(saved['file'],file.stem);self.assertEqual(saved['t'],'12:00:00')
 def test_digital_silence_is_not_sent_or_written(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);file=root/'20261101_120000_0001.wav'
   with wave.open(str(file),'wb') as audio:
    audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(bytes(32000))
   result=transcribe(file,root,root/'unused',send=lambda _:self.fail('silence submitted'))
   self.assertEqual(result['reason'],'digital_silence');self.assertFalse((root/'out').exists())
 def test_openai_compatible_audio_multipart(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);file=root/'20261101_120000_0001.wav'
   with wave.open(str(file),'wb') as audio:
    audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(b'\x01\x00'*16000)
   class Response:
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self):return b'{"text":"example"}'
   with patch.dict(os.environ,{'AUDIO_MEMORY_ASR_URL':'https://example.invalid/v1','AUDIO_MEMORY_ASR_KEY':'test-key','AUDIO_MEMORY_ASR_MODEL':'test-model','AUDIO_MEMORY_ASR_PROTOCOL':'openai_transcription'}),patch('urllib.request.urlopen',return_value=Response()) as send:
    row=transcribe(file,root,root/'unused')
    request=send.call_args.args[0];self.assertTrue(request.full_url.endswith('/audio/transcriptions'))
    self.assertIn(b'name="file"',request.data);self.assertIn(b'test-model',request.data);self.assertEqual(row['text'],'example')

if __name__=='__main__':unittest.main()
