import io
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import ocr_unit
import time_alignment_unit
import video_slides
import visual_worker

class VisualCancellationTests(unittest.TestCase):
    def test_worker_stops_before_launching_child_and_preserves_video(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);video=root/'record'/'camera'/'a.mp4';video.parent.mkdir(parents=True);video.write_bytes(b'original')
            stop=root/'stop';stop.touch();calls=[]
            result=visual_worker.run_one(video,root,invoke=lambda *a,**k:calls.append(a),stop_file=stop)
            self.assertEqual(result['stage'],'paused');self.assertEqual(calls,[]);self.assertEqual(video.read_bytes(),b'original')

    def test_video_stops_while_waiting_for_frame_and_terminates_decoder(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'video.mp4';source.write_bytes(b'fixture');stop=root/'stop'
            class Detector:
                def __init__(self,*_):self.items=[]
                def configure(self,*_):pass
            class Process:
                def __init__(self):self.stdout=io.BytesIO();self.stderr=io.BytesIO();self.terminated=False
                def poll(self):return 0 if self.terminated else None
                def terminate(self):self.terminated=True
                def wait(self,timeout=None):return 0
            process=Process();timer=threading.Timer(.3,stop.touch)
            with patch.object(video_slides,'SlideDetector',Detector),patch.object(video_slides,'video_size',return_value=(1,100,100,(2,2),(2,2))), \
                 patch.object(video_slides,'frame_pipe',return_value=process),patch.object(video_slides,'frame_reader',return_value=None):
                timer.start()
                try:
                    with self.assertRaises(InterruptedError):video_slides.extract(source,root,hardware=False,stop_file=stop)
                finally:timer.join()
            self.assertTrue(process.terminated);self.assertEqual(source.read_bytes(),b'fixture')

    def test_ocr_stop_terminates_owned_powershell(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);image=root/'frame.png';image.write_bytes(b'fixture');stop=root/'stop'
            class Process:
                def __init__(self,*_a,**_k):self.terminated=False;self.returncode=0
                def communicate(self,timeout=None):
                    if not self.terminated:stop.touch();raise subprocess.TimeoutExpired('fake',timeout)
                    return b'',b''
                def terminate(self):self.terminated=True
            with patch.object(ocr_unit.subprocess,'Popen',Process):
                with self.assertRaises(InterruptedError):ocr_unit._recognize([image],root,stop_file=stop)
            self.assertEqual(image.read_bytes(),b'fixture')

    def test_alignment_stops_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);index=root/'video.json';index.write_text(json.dumps({'processedSeconds':10}),encoding='utf-8');stop=root/'stop';stop.touch()
            with self.assertRaises(InterruptedError):time_alignment_unit.align(root,index,stop_file=stop)
            self.assertFalse((root/'out'/'alignments').exists())

if __name__=='__main__':unittest.main()
