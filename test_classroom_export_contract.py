import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from classroom_material_db import build
from material_store import latest_classroom_snapshot
from miniob_material_export import export


class ClassroomExportContractTests(unittest.TestCase):
    def test_build_export_and_failed_rebuild_preserve_database(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);session=root/'out'/'classroom-bridge'/'session';session.mkdir(parents=True)
            slide=root/'slide.png';Image.new('RGB',(10,10),'white').save(slide)
            video=root/'video.mp4';video.write_bytes(b'fixture')
            package={'schema':'classroom-session-bridge/v1','video':{'id':'session','path':str(video),'hash':'h','startAt':1,'endAt':2},
                     'slides':[{'id':'slide','path':str(slide),'firstSeenAt':1}],
                     'segments':[{'text':'fixture text','ts':1.5,'pptId':'slide','pptOffsetSeconds':.5}]}
            path=session/'notes-input.json';path.write_text(json.dumps(package),encoding='utf-8')
            (session.parent/'latest.json').write_text(json.dumps({'status':'ready_for_notes','sessionId':'session','path':'old-location'}),encoding='utf-8')
            database, counts=build(root);self.assertEqual((counts['sessions'],counts['slides'],counts['segments']),(1,1,1))
            snapshot=latest_classroom_snapshot(root);self.assertEqual(snapshot['segments'][0][1],'fixture text')
            output,count=export(root);self.assertEqual(count,1);self.assertIn('fixture text',(output/'schema-and-seed.sql').read_text(encoding='utf-8'))
            package['slides'][0]['path']=str(root/'missing.png');path.write_text(json.dumps(package),encoding='utf-8')
            with self.assertRaises(ValueError):build(root)
            self.assertEqual(latest_classroom_snapshot(root),snapshot)
            database.rename(database.with_suffix('.checked'))

    def test_relocated_package_uses_matching_recorded_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); session=root/'out'/'classroom-bridge'/'session'; session.mkdir(parents=True)
            video=root/'record'/'camera'/'video.mp4'; video.parent.mkdir(parents=True); video.write_bytes(b'video')
            slide=root/'out'/'scene'/'ppt'/'session'/'slide.png'; slide.parent.mkdir(parents=True); Image.new('RGB',(10,10),'white').save(slide)
            digest=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            package={'schema':'classroom-session-bridge/v1','video':{'id':'session','path':'Z:/old/record/camera/video.mp4','hash':digest(video),'startAt':1,'endAt':2},'slides':[{'id':'slide','path':'Z:/old/out/scene/ppt/session/slide.png','hash':digest(slide)}],'segments':[]}
            (session/'notes-input.json').write_text(json.dumps(package),encoding='utf-8')
            (session.parent/'latest.json').write_text(json.dumps({'status':'ready_for_notes','sessionId':'session','path':'old-location'}),encoding='utf-8')
            database,counts=build(root); self.assertEqual(counts['slides'],1)
            video.write_bytes(b'different video')
            with self.assertRaises(ValueError): build(root)

    def test_missing_database_is_not_created_by_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with self.assertRaises(FileNotFoundError):latest_classroom_snapshot(root)
            self.assertFalse((root/'out'/'material-index'/'materials.sqlite3').exists())

if __name__=='__main__': unittest.main()
