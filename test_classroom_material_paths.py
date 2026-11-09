import json
import tempfile
import unittest
import time
from pathlib import Path
from unittest.mock import patch

import classroom_materials


class ClassroomMaterialPathsTests(unittest.TestCase):
    def test_generated_material_uses_project_relative_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            day = root / 'out' / '20261031'; day.mkdir(parents=True)
            (day / 'timeline.jsonl').write_text(json.dumps({'text': 'test', 'file': 'test.wav', 'start': 0, 'end': 1}) + '\n', encoding='utf-8')
            with patch.object(classroom_materials, '__file__', str(root / 'classroom_materials.py')), \
                 patch('transcript_corrections.load', return_value={'records': {}}):
                output = classroom_materials.publish(day, root / 'published')
            text = output.read_text(encoding='utf-8')
            self.assertIn('out/20261031/timeline.jsonl', text)
            self.assertNotIn(str(root), text)


    def test_custom_data_root_controls_output_and_corrections(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);program=base/'program';program.mkdir();data=base/'data';day=data/'out'/'20261031';day.mkdir(parents=True)
            (day/'timeline.jsonl').write_text(json.dumps({'text':'test','file':'test.wav','start':0,'end':1})+'\n',encoding='utf-8')
            with patch.object(classroom_materials,'__file__',str(program/'classroom_materials.py')), \
                 patch('transcript_corrections.load',return_value={'records':{}}) as load:
                result=classroom_materials.publish(day,root=data)
            self.assertTrue(result.resolve().is_relative_to((data/'out'/'live-materials').resolve()))
            load.assert_called_once_with(data.resolve())
            self.assertFalse((program/'out').exists())

    def test_cloud_selection_uses_only_selected_data_root(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside:
            root=Path(folder); local=root/'out'/'day'; local.mkdir(parents=True)
            cloud=root/'out'/'cloud-asr-example'/'day'; cloud.mkdir(parents=True)
            for path,text in ((local,'local content'),(cloud,'cloud content')):
                (path/'timeline.jsonl').write_text(json.dumps({'text':text,'file':'test.wav','start':0,'end':1})+'\n',encoding='utf-8')
            (root/'transcription-control.json').write_text('{"mode":"cloud"}',encoding='utf-8')
            state={'active':True,'deadline':time.time()+300,'latestDayDir':str(cloud)}
            status=root/'cloud-asr-trial.json';status.write_text(json.dumps(state),encoding='utf-8')
            self.assertIn('cloud content',classroom_materials.publish(local,root=root).read_text(encoding='utf-8'))
            foreign=Path(outside);(foreign/'timeline.jsonl').write_text('{"text":"private"}\n',encoding='utf-8')
            state['latestDayDir']=str(foreign);status.write_text(json.dumps(state),encoding='utf-8')
            output=classroom_materials.publish(local,root=root).read_text(encoding='utf-8')
            self.assertIn('local content',output);self.assertNotIn('private',output)


if __name__ == '__main__':
    unittest.main()
