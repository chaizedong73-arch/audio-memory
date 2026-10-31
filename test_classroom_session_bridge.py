import json,tempfile,unittest
from pathlib import Path
from classroom_session_bridge import build

class BridgeTests(unittest.TestCase):
 def test_requires_mode_and_aligns_segments_to_same_video_slides(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);(root/'classroom-mode.json').write_text(json.dumps({'enabled':True}),encoding='utf-8')
   video=root/'record/camera/a.webm';video.parent.mkdir(parents=True);video.write_bytes(b'video')
   scene=root/'out/scene';scene.mkdir(parents=True);(scene/'last-recording.json').write_text(json.dumps({'id':'s','state':'saved','path':str(video),'startAt':100,'endAt':200}),encoding='utf-8')
   slide=root/'out/scene/ppt/run/1.png';slide.parent.mkdir(parents=True);slide.write_bytes(b'png');(slide.parent/'index.json').write_text(json.dumps({'items':[{'id':'p1','path':str(slide),'videoSession':'s','capturedAt':110,'firstSeenAt':110,'lastSeenAt':150,'contentHash':'x'}]}),encoding='utf-8')
   timeline=root/'out/20261030/timeline.jsonl';timeline.parent.mkdir(parents=True);timeline.write_text(json.dumps({'ts':120,'text':'讲解'})+'\n',encoding='utf-8')
   package,path=build(root);self.assertTrue(path.is_file());self.assertEqual(package['segments'][0]['pptId'],'p1')

if __name__=='__main__':unittest.main()
