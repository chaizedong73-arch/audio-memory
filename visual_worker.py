"""Watch completed camera recordings and invoke the independent video/OCR units."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from urllib.request import Request, urlopen
from urllib.error import URLError

ROOT = Path(__file__).resolve().parent


def _recording_start(root, video):
    """Use only a saved capture event explicitly referring to this video."""
    events = root / 'out' / 'scene' / 'events.jsonl'
    if not events.is_file() or not events.resolve().is_relative_to(root): return None
    found = None
    try:
        with events.open('rb') as stream:
            for raw in stream:
                try:
                    event = json.loads(raw.decode('utf-8'))
                    ts = event.get('startAt')
                    if (event.get('event') == 'record-end' and event.get('state') == 'saved'
                            and isinstance(ts, (int, float)) and math.isfinite(ts) and ts > 0
                            and Path(event.get('path', '')).resolve() == video):
                        found = ts
                except (ValueError, TypeError, AttributeError, OSError, UnicodeDecodeError):
                    continue
    except OSError:
        return None
    return found


def _alignment_fingerprint(root, start):
    sources = []
    for path in sorted((root / 'out').glob('**/timeline.jsonl')):
        try:
            if path.resolve().is_relative_to(root):
                stat = path.stat(); sources.append((path.relative_to(root).as_posix(), stat.st_size, stat.st_mtime_ns))
        except OSError:
            continue
    return hashlib.sha256(json.dumps([start, sources], sort_keys=True).encode()).hexdigest()


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class VisualStopped(Exception):
    pass


def publish(root, state, stop_file=None):
    if stop_file and Path(stop_file).exists(): return
    if state.get('indexPending', True):
        try:
            from material_bridge import sync
            report = sync(root, visual_only=True, stop_file=stop_file)
            state['indexPending'] = bool(report['errors'])
            if state['indexPending']:
                state['indexWarning'] = '材料登记尚未完成，将自动重试'
            else:
                state.pop('indexWarning', None)
        except InterruptedError:
            return
        except Exception:
            state['indexPending'] = True
            state['indexWarning'] = '材料登记失败，将自动重试'
    if state.get('gatewayPending', True) and not (stop_file and Path(stop_file).exists()):
        try:
            token = (root / 'out' / 'ai-gateway' / 'access-token').read_text(encoding='utf-8').strip()
            request = Request('http://127.0.0.1:8768/v1/refresh', data=b'{}',
                              headers={'Authorization':'Bearer ' + token, 'Content-Type':'application/json'}, method='POST')
            with urlopen(request, timeout=10) as response:
                if response.status != 200: raise OSError('gateway refresh failed')
            state['gatewayPending'] = False
            state.pop('gatewayWarning', None)
        except (OSError, ValueError, URLError):
            state['gatewayPending'] = True
            state['gatewayWarning'] = '材料网关未更新，将自动重试'


def run_one(video, root=ROOT, invoke=subprocess.run, stop_file=None):
    root = Path(root).resolve(); video = Path(video).resolve(strict=True)
    if not video.is_file() or not video.is_relative_to(root / 'record' / 'camera') or '.partial.' in video.name:
        raise ValueError('Expected a completed local camera video')
    stat = video.stat(); source = video.relative_to(root).as_posix()
    key = hashlib.sha256(f'{source}\0{stat.st_size}\0{stat.st_mtime_ns}'.encode()).hexdigest()
    state_path = root / 'out' / 'visual-tasks' / (key + '.json')
    state = json.loads(state_path.read_text(encoding='utf-8-sig')) if state_path.exists() else {'source': source, 'stage': 'new'}
    start = _recording_start(root, video)
    fingerprint = _alignment_fingerprint(root, start)
    if state.get('stage') == 'completed' and state.get('alignmentFingerprint') == fingerprint:
        if state.get('indexPending', True) or state.get('gatewayPending', True):
            publish(root, state, stop_file); _save(state_path, state)
        return state
    child_env = {**os.environ, 'PYTHONUTF8': '1'}
    def check_stop():
        if stop_file and Path(stop_file).exists(): raise VisualStopped()
    def command_with_stop(command):
        return command + (['--stop-file', str(stop_file)] if stop_file else [])
    try:
        check_stop()
        if not state.get('index'):
            result = invoke(command_with_stop([sys.executable, str(ROOT / 'video_unit.py'), str(video), '--root', str(root)]),
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=1800, env=child_env)
            check_stop()
            if result.returncode: raise RuntimeError('video_unit_failed')
            extraction = json.loads(result.stdout)
            if extraction.get('truncated'): raise RuntimeError('video_extraction_truncated')
            index = Path(extraction['index']).resolve()
            if not index.is_relative_to(root) or not index.is_file(): raise ValueError('invalid index')
            state.update(index=str(index), stage='extracted'); _save(state_path, state)
        index = Path(state['index']).resolve()
        if not index.is_relative_to(root) or not index.is_file(): raise ValueError('invalid index')
        items = json.loads(index.read_text(encoding='utf-8-sig')).get('items', [])
        images = [str(Path(item['path']).resolve()) for item in items]
        if any(not Path(p).is_relative_to(root) for p in images): raise ValueError('image outside project')
        empty = state.get('emptyPages', 0)
        if not state.get('ocrDone'):
            empty = 0
            for offset in range(0, len(images), 20):
                check_stop()
                ocr = invoke(command_with_stop([sys.executable, str(ROOT / 'ocr_unit.py'), *images[offset:offset+20], '--root', str(root)]),
                             capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300, env=child_env)
                check_stop()
                if ocr.returncode: raise RuntimeError('ocr_unit_failed')
                empty += int(json.loads(ocr.stdout).get('empty', 0))
            state.update(ocrDone=True, emptyPages=empty, stage='ocr_completed'); _save(state_path, state)
        video_index = index.parent / 'video.json'
        alignment_command = [sys.executable, str(ROOT / 'time_alignment_unit.py'), str(video_index), '--root', str(root)]
        if start is not None: alignment_command += ['--video-start', str(start)]
        check_stop()
        alignment = invoke(command_with_stop(alignment_command), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300, env=child_env)
        check_stop()
        if alignment.returncode: raise RuntimeError('alignment_unit_failed')
        aligned = json.loads(alignment.stdout)
        alignment_path = Path(aligned['output']).resolve()
        if not alignment_path.is_file() or not alignment_path.is_relative_to(root): raise ValueError('invalid alignment output')
        state.update(alignment=str(alignment_path), alignmentWarnings=aligned.get('warnings', []), alignmentFingerprint=fingerprint)
        state.update(stage='completed', pages=len(images), indexPending=True, gatewayPending=True); state.pop('error', None)
        if not images: state['warning'] = 'no_stable_slides'
        elif empty: state['warning'] = 'ocr_empty_pages:' + str(empty)
        else: state.pop('warning', None)
    except VisualStopped:
        state.update(stage='paused')
        state.pop('error', None)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
        reason = str(error) if isinstance(error, RuntimeError) and str(error) in ('video_unit_failed', 'video_extraction_truncated', 'ocr_unit_failed', 'alignment_unit_failed') else type(error).__name__
        state.update(stage='failed', error=reason)
    _save(state_path, state)
    if state.get('stage') == 'completed':
        publish(root, state, stop_file); _save(state_path, state)
    return state


def scan(root=ROOT, stop_file=None):
    root = Path(root).resolve()
    result = []
    folder = root / 'record' / 'camera'
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        if stop_file and Path(stop_file).exists(): break
        if not path.is_file() or path.suffix.lower() not in {'.webm', '.mp4', '.mov', '.mkv'} or '.partial.' in path.name.lower(): continue
        try:
            result.append(run_one(path, root, stop_file=stop_file) if stop_file else run_one(path, root))
        except (OSError, ValueError) as error:
            result.append({'stage': 'failed', 'error': type(error).__name__})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--stop-file', type=Path)
    parser.add_argument('--ready-file', type=Path)
    args = parser.parse_args()
    import singlelock
    lock = singlelock.acquire(str(args.root.resolve() / '.locks' / 'visual-worker.lock'))
    if lock is None:
        print(json.dumps({'unit': 'visual-worker', 'error': 'already_running'}), flush=True)
        raise SystemExit(1)
    try:
        if args.ready_file:
            args.ready_file.write_text(str(os.getpid()), encoding='ascii')
        while True:
            if args.stop_file and args.stop_file.exists(): break
            results = scan(args.root, args.stop_file)
            print(json.dumps({'unit': 'visual-worker', 'version': 1, 'jobs': results}, ensure_ascii=False), flush=True)
            if not args.watch: raise SystemExit(1 if any(x.get('stage') == 'failed' for x in results) else 0)
            for _ in range(15):
                if args.stop_file and args.stop_file.exists(): break
                time.sleep(.2)
    finally:
        if args.ready_file:
            args.ready_file.unlink(missing_ok=True)
        lock.close()
