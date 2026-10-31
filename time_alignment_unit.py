"""Build evidence-based video-frame/subtitle time candidates without guessing PPT matches."""
import argparse
import json
import math
import os
from pathlib import Path
import time
import uuid

ROOT = Path(__file__).resolve().parent


def align(root, video_index, video_start=None, stop_file=None):
    if stop_file and Path(stop_file).exists(): raise InterruptedError('alignment stopped')
    root = Path(root).resolve()
    video_index = Path(video_index).resolve(strict=True)
    if not video_index.is_file() or not video_index.is_relative_to(root):
        raise ValueError('Video index must be inside the project')
    if video_start is not None and (not isinstance(video_start, (int, float)) or not math.isfinite(video_start) or video_start <= 0):
        raise ValueError('Video start must be an absolute timestamp')
    data = json.loads(video_index.read_text(encoding='utf-8-sig'))
    duration = float(data['processedSeconds'])
    if not math.isfinite(duration) or duration <= 0: raise ValueError('Invalid video duration')
    occurrences = []
    for item in data.get('occurrences', []):
        begin, end = float(item['startSeconds']), float(item['endSeconds'])
        if not math.isfinite(begin) or not math.isfinite(end) or not (0 <= begin < end <= duration):
            raise ValueError('Invalid frame interval')
        occurrences.append({'pageId': str(item['pageId']), 'startSeconds': begin, 'endSeconds': end})
    result = {'schema': 'video-subtitle-alignment/v1', 'createdAt': time.time(),
              'videoIndex': video_index.relative_to(root).as_posix(), 'videoStart': video_start,
              'occurrences': occurrences, 'segments': [], 'warnings': [],
              'meaning': 'time-overlap candidates only; not confirmed matches to original PPT'}
    if not occurrences: result['warnings'].append('no_video_slides')
    if video_start is None:
        result['warnings'].append('video_start_unknown')
        return result
    end_at = video_start + duration
    for timeline in sorted((root / 'out').glob('**/timeline.jsonl')):
        if stop_file and Path(stop_file).exists(): raise InterruptedError('alignment stopped')
        source = timeline.relative_to(root).as_posix()
        if not timeline.resolve().is_relative_to(root):
            result['warnings'].append('transcript_source_outside_project'); continue
        try:
            with timeline.open('rb') as stream:
                for line_no, raw in enumerate(stream, 1):
                    if stop_file and Path(stop_file).exists(): raise InterruptedError('alignment stopped')
                    try:
                        row = json.loads(raw.decode('utf-8'))
                        ts = row.get('ts'); text = row.get('text')
                        if not isinstance(ts, (int, float)) or not math.isfinite(ts) or not isinstance(text, str): continue
                        if not video_start <= ts < end_at: continue
                        duration_s = max(0.0, float(row.get('end', 0)) - float(row.get('start', 0)))
                        if not math.isfinite(duration_s): raise ValueError('invalid duration')
                        begin = ts - video_start
                        finish = min(duration, begin + duration_s)
                        refs = [x['pageId'] for x in occurrences if x['startSeconds'] <= begin < x['endSeconds'] or
                                (finish > begin and x['startSeconds'] < finish and x['endSeconds'] > begin)]
                        result['segments'].append({'source': source, 'line': line_no, 'ts': ts,
                                                   'offsetSeconds': round(begin, 3), 'pageCandidates': list(dict.fromkeys(refs))})
                    except (ValueError, TypeError, AttributeError, UnicodeDecodeError):
                        result['warnings'].append('invalid_transcript_record'); continue
        except InterruptedError:
            raise
        except OSError:
            result['warnings'].append('transcript_unreadable')
    if not result['segments']: result['warnings'].append('no_timed_subtitles')
    result['warnings'] = sorted(set(result['warnings']))
    return result


def save(root, result):
    folder = Path(root).resolve() / 'out' / 'alignments'; folder.mkdir(parents=True, exist_ok=True)
    path = folder / (uuid.uuid4().hex + '.json'); temporary = path.with_suffix('.tmp')
    try:
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video_index', type=Path); parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--video-start', type=float, default=None)
    parser.add_argument('--stop-file', type=Path)
    args = parser.parse_args()
    try:
        result = align(args.root, args.video_index, args.video_start, args.stop_file)
        if args.stop_file and args.stop_file.exists(): raise InterruptedError('alignment stopped')
        output = save(args.root, result)
        print(json.dumps({'unit': 'time-alignment', 'version': 1, 'output': str(output), 'warnings': result['warnings'], 'segments': len(result['segments'])}, ensure_ascii=False))
    except InterruptedError:
        print(json.dumps({'unit': 'time-alignment', 'version': 1, 'error': 'stopped'}, ensure_ascii=False))
        raise SystemExit(130)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'unit': 'time-alignment', 'version': 1, 'error': type(error).__name__}, ensure_ascii=False))
        raise SystemExit(1)
