"""Bridge saved files to the local material index without controlling producers."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import wave

from material_store import register_material, update_module
from transcript_corrections import effective, load

ROOT = Path(__file__).resolve().parent


def _hash_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def sync(root=ROOT, visual_only=False, stop_file=None):
    root = Path(root).resolve()
    def check_stop():
        if stop_file and Path(stop_file).exists(): raise InterruptedError('stopped')
    report = {'audio': 0, 'transcript': 0, 'slides': 0, 'ocr': 0, 'alignment': 0, 'feedback': 0, 'errors': []}
    try:
        corrections = None if visual_only else load(root)
    except (OSError, ValueError) as error:
        corrections = None
        report['errors'].append({'source': 'transcript-corrections.json', 'kind': type(error).__name__})
    for path in ([] if visual_only else sorted((root / 'record').glob('*.wav'))):
        source = path.relative_to(root).as_posix()
        try:
            if not path.resolve().is_relative_to(root): raise ValueError('source outside project')
            with wave.open(str(path), 'rb') as audio:
                meta = {'sampleRate': audio.getframerate(), 'frames': audio.getnframes(), 'channels': audio.getnchannels()}
            identity = hashlib.sha256(('audio\0' + source).encode()).hexdigest()[:24]
            register_material(identity, 'audio', source, _hash_file(path), meta, root)
            report['audio'] += 1
        except InterruptedError:
            raise
        except Exception as error:
            report['errors'].append({'source': source, 'kind': type(error).__name__})
    for path in ([] if visual_only else sorted((root / 'out').glob('**/timeline.jsonl'))):
        source = path.relative_to(root).as_posix()
        try:
            if not path.resolve().is_relative_to(root): raise ValueError('source outside project')
            with path.open('rb') as stream:
                for line_no, raw in enumerate(stream, 1):
                    try:
                        row = json.loads(raw.decode('utf-8'))
                        if not isinstance(row, dict) or not isinstance(row.get('text'), str): raise ValueError('invalid record')
                        if corrections is not None:
                            try: row = effective(row, path, corrections)
                            except (KeyError, ValueError, TypeError): pass
                        locator = f'line:{line_no}'
                        identity = hashlib.sha256(f'transcript_segment\0{source}\0{locator}'.encode()).hexdigest()[:24]
                        version = hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                        register_material(identity, 'transcript_segment', source, version, {'locator': locator, 'record': row}, root)
                        report['transcript'] += 1
                    except InterruptedError:
                        raise
                    except Exception as error:
                        report['errors'].append({'source': source, 'line': line_no, 'kind': type(error).__name__})
        except (OSError, ValueError) as error:
            report['errors'].append({'source': source, 'kind': type(error).__name__})
    for index in sorted((root / 'out' / 'scene' / 'ppt').glob('*/index.json')):
        check_stop()
        try:
            if not index.resolve().is_relative_to(root): raise ValueError('source outside project')
            document = json.loads(index.read_text(encoding='utf-8-sig'))
            for item in document.get('items', []):
                check_stop()
                try:
                    image = Path(item['path'])
                    image = (image if image.is_absolute() else root / image).resolve()
                    source = image.relative_to(root).as_posix()
                    content_hash = _hash_file(image)
                    locator = str(item.get('id', ''))
                    identity = hashlib.sha256(f'ppt_slide\0{source}\0{locator}\0{content_hash}\0'.encode()).hexdigest()[:24]
                    metadata = {k: item[k] for k in ('id', 'firstSeenAt', 'capturedAt', 'lastSeenAt', 'videoSession', 'videoOffsetSeconds') if k in item}
                    register_material(identity, 'ppt_slide', source, content_hash, metadata, root)
                    report['slides'] += 1
                except InterruptedError:
                    raise
                except Exception as error:
                    report['errors'].append({'source': index.relative_to(root).as_posix(), 'kind': type(error).__name__})
        except InterruptedError:
            raise
        except Exception as error:
            report['errors'].append({'source': index.relative_to(root).as_posix(), 'kind': type(error).__name__})
    catalog = root / 'out' / 'ppt-concepts' / 'catalog.json'
    if catalog.exists():
        try:
            if not catalog.resolve().is_relative_to(root): raise ValueError('source outside project')
            data = json.loads(catalog.read_text(encoding='utf-8-sig'))
            for image_path, entry in data.get('pages', {}).items():
                check_stop()
                try:
                    image = Path(image_path)
                    image = (image if image.is_absolute() else root / image).resolve()
                    source = image.relative_to(root).as_posix()
                    ocr_id = str(entry['hash'])
                    if not ocr_id or any(c not in '0123456789abcdefABCDEF' for c in ocr_id): raise ValueError('invalid OCR id')
                    ocr_file = (catalog.parent / (ocr_id + '.json')).resolve()
                    if not ocr_file.is_relative_to(root): raise ValueError('source outside project')
                    payload = json.loads(ocr_file.read_text(encoding='utf-8-sig'))
                    text = payload.get('text', '')
                    if not isinstance(text, str) or not text.strip(): continue
                    content_hash = _hash_file(image)
                    identity = hashlib.sha256(f'ppt_ocr\0{source}\0{ocr_id}\0{content_hash}\0'.encode()).hexdigest()[:24]
                    register_material(identity, 'ppt_ocr', source, content_hash, {'text': text, 'terms': payload.get('terms', []), 'extractor': 'ppt_concepts'}, root)
                    report['ocr'] += 1
                except InterruptedError:
                    raise
                except Exception as error:
                    report['errors'].append({'source': catalog.relative_to(root).as_posix(), 'kind': type(error).__name__})
        except InterruptedError:
            raise
        except Exception as error:
            report['errors'].append({'source': catalog.relative_to(root).as_posix(), 'kind': type(error).__name__})
    for path in sorted((root / 'out' / 'alignments').glob('*.json')):
        check_stop()
        source = path.relative_to(root).as_posix()
        try:
            if not path.resolve().is_relative_to(root): raise ValueError('source outside project')
            record = json.loads(path.read_text(encoding='utf-8-sig'))
            if record.get('schema') != 'video-subtitle-alignment/v1': raise ValueError('invalid alignment')
            identity = hashlib.sha256(('alignment\0' + source).encode()).hexdigest()[:24]
            register_material(identity, 'alignment', source, _hash_file(path), {'record': record}, root)
            report['alignment'] += 1
        except InterruptedError:
            raise
        except Exception as error:
            report['errors'].append({'source': source, 'kind': type(error).__name__})
    for path in ([] if visual_only else sorted((root / 'out' / 'ai-gateway' / 'feedback').glob('*.json'))):
        source = path.relative_to(root).as_posix()
        try:
            if not path.resolve().is_relative_to(root): raise ValueError('source outside project')
            record = json.loads(path.read_text(encoding='utf-8-sig'))
            feedback_id = record.get('id')
            if not isinstance(feedback_id, str) or len(feedback_id) != 32 or any(c not in '0123456789abcdef' for c in feedback_id):
                raise ValueError('invalid feedback identity')
            identity = hashlib.sha256(('feedback\0' + feedback_id).encode()).hexdigest()[:24]
            register_material(identity, 'feedback', source, _hash_file(path), {'record': record}, root)
            report['feedback'] += 1
        except InterruptedError:
            raise
        except Exception as error:
            report['errors'].append({'source': source, 'kind': type(error).__name__})
    try:
        update_module('material_bridge_visual' if visual_only else 'material_bridge', 'error' if report['errors'] else 'ready',
                      f"audio={report['audio']}, transcript={report['transcript']}, slides={report['slides']}, ocr={report['ocr']}, alignment={report['alignment']}, feedback={report['feedback']}, errors={len(report['errors'])}", root)
    except InterruptedError:
        raise
    except Exception:
        # A broken database must not stop the independent recording process.
        report['errors'].append({'source': 'material-database', 'kind': 'StatusUnavailable'})
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Index saved audio and transcript files')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--stop-file', type=Path)
    args = parser.parse_args()
    while True:
        result = sync(args.root)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if not args.watch or (args.stop_file and args.stop_file.exists()):
            raise SystemExit(1 if result['errors'] else 0)
        for _ in range(50):
            if args.stop_file and args.stop_file.exists(): break
            time.sleep(.2)
