"""Watch completed camera recordings and invoke the independent video/OCR units."""
from data_location import data_root as default_data_root
from gateway_credentials import read_gateway_token
from material_exchange import MaterialExchange
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
    return MaterialExchange(root).video_start(video)


def _alignment_fingerprint(root, start):
    sources = MaterialExchange(root).transcript_fingerprint()
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
            token = read_gateway_token(root)
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
    root = Path(root).resolve()
    video, source = MaterialExchange(root).video_source(video)
    stat = video.stat()
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
            index, _, _ = MaterialExchange(root).video_slide_index(extraction['index'])
            state.update(index=str(index), stage='extracted'); _save(state_path, state)
        index, images, video_index = MaterialExchange(root).video_slide_index(state['index'])
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


def list_tasks(root=ROOT):
    """Return bounded public task status, retaining source checks."""
    root = Path(root).resolve(); folder = root / 'out' / 'visual-tasks'
    paths = sorted(folder.glob('*.json'), key=lambda path: path.stat().st_mtime, reverse=True)[:100]
    tasks = []
    for path in paths:
        if not path.resolve().is_relative_to(root): continue
        try: state = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError, UnicodeDecodeError): continue
        if isinstance(state, dict):
            tasks.append({key: state[key] for key in ('source', 'stage', 'pages', 'error', 'warning', 'alignmentWarnings', 'indexWarning', 'gatewayWarning') if key in state})
    return {'schema': 'visual-tasks/v1', 'items': tasks}


def scan(root=ROOT, stop_file=None):
    root = Path(root).resolve()
    result = []
    for path in MaterialExchange(root).videos():
        if stop_file and Path(stop_file).exists(): break
        try:
            result.append(run_one(path, root, stop_file=stop_file) if stop_file else run_one(path, root))
        except (OSError, ValueError) as error:
            result.append({'stage': 'failed', 'error': type(error).__name__})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=default_data_root())
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
