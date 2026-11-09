"""Recognize supplied local images independently and publish OCR result files."""
from data_location import data_root as default_data_root
from ocr_store import OcrStore
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent


def _save(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _recognize(paths, directory, stop_file=None):
    with tempfile.TemporaryDirectory(prefix='ocr-', dir=directory) as tmp:
        input_path, output_path = Path(tmp) / 'input.json', Path(tmp) / 'output.json'
        input_path.write_text(json.dumps([str(p) for p in paths], ensure_ascii=False), encoding='utf-8')
        if stop_file and Path(stop_file).exists(): raise InterruptedError('OCR stopped')
        command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                   str(Path(__file__).with_name('ppt_ocr.ps1')), '-InputFile', str(input_path),
                   '-OutputFile', str(output_path)]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + 120
        while True:
            try:
                process.communicate(timeout=.2)
                break
            except subprocess.TimeoutExpired:
                if stop_file and Path(stop_file).exists():
                    process.terminate(); process.communicate()
                    raise InterruptedError('OCR stopped')
                if time.monotonic() >= deadline:
                    process.kill(); process.communicate()
                    raise subprocess.TimeoutExpired(command, 120)
        if process.returncode:
            raise RuntimeError('Windows OCR failed; check installed OCR language')
        return json.loads(output_path.read_text(encoding='utf-8-sig'))


def run(images, root=ROOT, recognize=_recognize, stop_file=None):
    root = Path(root).resolve()
    if not images: raise ValueError('At least one image is required')
    paths = [Path(p).resolve(strict=True) for p in images]
    if any(not p.is_file() or not p.is_relative_to(root) for p in paths):
        raise ValueError('Images must be files inside the project root')
    store = OcrStore(root); folder = store.folder
    store.catalog()  # Validate before spending time on recognition.
    pages, stored_results = {}, {}
    output = recognize(paths, folder, stop_file=stop_file) if stop_file else recognize(paths, folder)
    if not isinstance(output, list): raise ValueError('OCR engine returned invalid output')
    by_path = {str(item.get('path')): item for item in output if isinstance(item, dict)}
    result = {'unit': 'ocr', 'version': 1, 'completed': 0, 'empty': 0, 'errors': []}
    for path in paths:
        if stop_file and Path(stop_file).exists(): raise InterruptedError('OCR stopped')
        item = by_path.get(str(path))
        if not item or item.get('error') or not isinstance(item.get('text'), str):
            result['errors'].append({'source': path.relative_to(root).as_posix(), 'error': 'ocr_failed'})
            continue
        key = hashlib.sha256(path.read_bytes()).hexdigest()
        text = item['text']
        if not text.strip(): result['empty'] += 1
        terms = list(dict.fromkeys(re.findall(r'[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*|[α-ωΑ-Ω]|[\u4e00-\u9fff]{2,8}', text)))[:250]
        stamp = [path.stat().st_size, path.stat().st_mtime_ns]
        stored_results[key] = {**item, 'hash': key, 'terms': terms, 'indexedAt': time.time()}
        pages[str(path)] = {'hash': key, 'stamp': stamp}
        result['completed'] += 1
    store.commit(pages, stored_results)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('images', nargs='+', type=Path)
    parser.add_argument('--root', type=Path, default=default_data_root())
    parser.add_argument('--stop-file', type=Path)
    args = parser.parse_args()
    try:
        result = run(args.images, args.root, stop_file=args.stop_file)
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(1 if result['errors'] else 0)
    except InterruptedError:
        print(json.dumps({'unit': 'ocr', 'version': 1, 'errors': [{'error': 'stopped'}]}, ensure_ascii=False))
        raise SystemExit(130)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({'unit': 'ocr', 'version': 1, 'completed': 0, 'errors': [{'error': type(error).__name__}]}, ensure_ascii=False))
        raise SystemExit(1)
