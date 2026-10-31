import json
import tempfile
import unittest
from pathlib import Path

from time_alignment_unit import align


class AlignmentTests(unittest.TestCase):
    def test_does_not_guess_missing_start_and_preserves_frame_offsets(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); index=root/'video.json'
            index.write_text(json.dumps({'processedSeconds':10,'occurrences':[{'pageId':'p','startSeconds':2,'endSeconds':8}]}),encoding='utf-8')
            result=align(root,index)
            self.assertEqual(result['warnings'],['video_start_unknown'])
            self.assertEqual(result['occurrences'][0]['startSeconds'],2)
            self.assertEqual(result['segments'],[])

    def test_matches_only_overlapping_intervals_and_exposes_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); index=root/'video.json'
            index.write_text(json.dumps({'processedSeconds':10,'occurrences':[{'pageId':'p','startSeconds':2,'endSeconds':5}]}),encoding='utf-8')
            timeline=root/'out'/'day'/'timeline.jsonl';timeline.parent.mkdir(parents=True)
            rows=[{'ts':101,'start':1,'end':1,'text':'before'}, {'ts':104,'start':4,'end':6,'text':'during'}, {'ts':107,'start':7,'end':7,'text':'after'}]
            timeline.write_text('\n'.join(json.dumps(r) for r in rows)+'\n',encoding='utf-8')
            result=align(root,index,100)
            self.assertEqual([r['pageCandidates'] for r in result['segments']],[[],['p'],[]])
            self.assertIn('not confirmed',result['meaning'])

    def test_missing_slides_does_not_discard_timed_transcript(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); index=root/'video.json'
            index.write_text(json.dumps({'processedSeconds':10,'occurrences':[]}),encoding='utf-8')
            timeline=root/'out'/'day'/'timeline.jsonl';timeline.parent.mkdir(parents=True)
            timeline.write_text(json.dumps({'ts':101,'text':'valid'})+'\n',encoding='utf-8')
            result=align(root,index,100)
            self.assertIn('no_video_slides',result['warnings'])
            self.assertEqual(result['segments'][0]['pageCandidates'],[])


if __name__=='__main__': unittest.main()
