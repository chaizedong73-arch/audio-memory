"""Independently extract stable slide screenshots from a completed local video."""
from data_location import data_root as default_data_root
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


def run(video, root=ROOT, interval=1.0, stop_file=None):
    video = Path(video).resolve(strict=True)
    if not video.is_file(): raise ValueError('Video must be a file')
    from video_slides import extract
    # The extraction engine emits its own progress and result to stdout; route
    # that to stderr so this unit's stdout stays a machine-readable protocol.
    from contextlib import redirect_stdout
    with redirect_stdout(sys.stderr):
        result = extract(video, Path(root).resolve(), interval=interval, stop_file=stop_file)
    return {'unit': 'video-slides', 'version': 1, 'index': result['index'],
            'uniquePages': result['uniquePages'], 'truncated': result['truncated']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('--root', type=Path, default=default_data_root())
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--stop-file', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.video, args.root, args.interval, args.stop_file), ensure_ascii=False))
    except InterruptedError:
        print(json.dumps({'unit': 'video-slides', 'version': 1, 'error': 'stopped'}, ensure_ascii=False))
        raise SystemExit(130)
    except (OSError, ValueError, RuntimeError, ImportError) as error:
        print(json.dumps({'unit': 'video-slides', 'version': 1, 'error': type(error).__name__}, ensure_ascii=False))
        raise SystemExit(1)
