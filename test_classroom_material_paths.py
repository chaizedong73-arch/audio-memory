import json
import tempfile
import unittest
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


if __name__ == '__main__':
    unittest.main()
