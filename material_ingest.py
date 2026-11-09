"""Ingest recordings and transcripts into the material index.

This adapter owns the legacy file layout; callers receive counts and errors.
"""
import hashlib
import json
from pathlib import Path
import wave
from material_store import register_material
from material_exchange import MaterialExchange
from transcript_corrections import CorrectionConflict, effective, load


def _hash_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def ingest_recordings_and_transcripts(root, visual_only=False, register=register_material, exchange=None, only_mobile=None):
    root = Path(root).resolve()
    exchange = exchange or MaterialExchange(root)
    report = {'audio': 0, 'transcript': 0, 'errors': []}
    audio_sources, timeline_sources = (None, None)
    if only_mobile is not None:
        audio, timeline = exchange.mobile_sources(*only_mobile)
        audio_sources, timeline_sources = [audio], [timeline]
    try:
        corrections = None if visual_only else load(root)
    except (OSError, ValueError) as error:
        corrections = None
        report['errors'].append({'source': 'transcript-corrections.json', 'kind': type(error).__name__})
    for path in ([] if visual_only else (exchange.ingest_audio_sources() if audio_sources is None else audio_sources)):
        try:
            source = path.relative_to(root).as_posix()
        except ValueError:
            report['errors'].append({'source': path.name, 'kind': 'SourceOutsideProject'})
            continue
        try:
            if not path.resolve().is_relative_to(root): raise ValueError('source outside project')
            with wave.open(str(path), 'rb') as audio:
                meta = {'sampleRate': audio.getframerate(), 'frames': audio.getnframes(), 'channels': audio.getnchannels()}
            identity = hashlib.sha256(('audio\0' + source).encode()).hexdigest()[:24]
            register(identity, 'audio', source, _hash_file(path), meta, root)
            report['audio'] += 1
        except InterruptedError:
            raise
        except Exception as error:
            report['errors'].append({'source': source, 'kind': type(error).__name__})
    for source, line_no, row, error in ([] if visual_only else exchange.transcript_rows(paths=timeline_sources)):
        if error:
            entry = {'source': source, 'kind': 'ValueError' if error == 'invalid_transcript_record' else error}
            if line_no: entry['line'] = line_no
            report['errors'].append(entry)
            continue
        path = root / source
        try:
            if not isinstance(row, dict) or not isinstance(row.get('text'), str): raise ValueError('invalid record')
            if corrections is not None:
                try: row = effective(row, path, corrections)
                except CorrectionConflict:
                    report['errors'].append({'source': source, 'line': line_no, 'kind': 'CorrectionConflict'})
                    continue
                except (KeyError, ValueError, TypeError): pass
            locator = f'line:{line_no}'
            identity = hashlib.sha256(f'transcript_segment\0{source}\0{locator}'.encode()).hexdigest()[:24]
            version = hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            register(identity, 'transcript_segment', source, version, {'locator': locator, 'record': row}, root)
            report['transcript'] += 1
        except InterruptedError:
            raise
        except Exception as error:
            report['errors'].append({'source': source, 'line': line_no, 'kind': type(error).__name__})
    return report


def ingest_visual_and_feedback(root, visual_only=False, stop_file=None, register=register_material, exchange=None):
    root = Path(root).resolve()
    exchange = exchange or MaterialExchange(root)
    report = {'slides': 0, 'ocr': 0, 'alignment': 0, 'feedback': 0, 'errors': []}
    try: exchange.validate_visual_root()
    except ValueError:
        report['errors'].append({'source': 'visual-storage', 'kind': 'SourceOutsideProject'})
        return report
    def check_stop():
        if stop_file and Path(stop_file).exists(): raise InterruptedError('stopped')
    for index in exchange.visual_slide_indexes():
        check_stop()
        try:
            if not index.resolve().is_relative_to(root): raise ValueError('source outside project')
            document = json.loads(index.read_text(encoding='utf-8-sig'))
            for item in document.get('items', []):
                check_stop()
                try:
                    image = exchange.slide_file(item['path'], item.get('contentHash'))
                    source = image.relative_to(root).as_posix()
                    content_hash = _hash_file(image)
                    locator = str(item.get('id', ''))
                    identity = hashlib.sha256(f'ppt_slide\0{source}\0{locator}\0{content_hash}\0'.encode()).hexdigest()[:24]
                    metadata = {k: item[k] for k in ('id', 'firstSeenAt', 'capturedAt', 'lastSeenAt', 'videoSession', 'videoOffsetSeconds') if k in item}
                    register(identity, 'ppt_slide', source, content_hash, metadata, root)
                    report['slides'] += 1
                except InterruptedError:
                    raise
                except Exception as error:
                    report['errors'].append({'source': index.relative_to(root).as_posix(), 'kind': type(error).__name__})
        except InterruptedError:
            raise
        except Exception as error:
            report['errors'].append({'source': index.relative_to(root).as_posix(), 'kind': type(error).__name__})
    try: catalog = exchange.ocr_catalog()
    except (ValueError, OSError) as error:
        report['errors'].append({'source': 'ocr-catalog', 'kind': type(error).__name__})
        catalog = None
    if catalog and catalog.exists():
        try:
            if not catalog.resolve().is_relative_to(root): raise ValueError('source outside project')
            data = json.loads(catalog.read_text(encoding='utf-8-sig'))
            for image_path, entry in data.get('pages', {}).items():
                check_stop()
                try:
                    ocr_id = str(entry['hash'])
                    image = exchange.resolve_material(image_path, ocr_id)
                    source = image.relative_to(root).as_posix()
                    if not ocr_id or any(c not in '0123456789abcdefABCDEF' for c in ocr_id): raise ValueError('invalid OCR id')
                    ocr_file = (catalog.parent / (ocr_id + '.json')).resolve()
                    if not ocr_file.is_relative_to(root): raise ValueError('source outside project')
                    payload = json.loads(ocr_file.read_text(encoding='utf-8-sig'))
                    text = payload.get('text', '')
                    if not isinstance(text, str) or not text.strip(): continue
                    content_hash = _hash_file(image)
                    identity = hashlib.sha256(f'ppt_ocr\0{source}\0{ocr_id}\0{content_hash}\0'.encode()).hexdigest()[:24]
                    register(identity, 'ppt_ocr', source, content_hash, {'text': text, 'terms': payload.get('terms', []), 'extractor': 'ppt_concepts'}, root)
                    report['ocr'] += 1
                except InterruptedError:
                    raise
                except Exception as error:
                    report['errors'].append({'source': catalog.relative_to(root).as_posix(), 'kind': type(error).__name__})
        except InterruptedError:
            raise
        except Exception as error:
            report['errors'].append({'source': catalog.relative_to(root).as_posix(), 'kind': type(error).__name__})
    for path in exchange.alignment_results():
        check_stop()
        source = path.relative_to(root).as_posix()
        try:
            if not path.resolve().is_relative_to(root): raise ValueError('source outside project')
            record = json.loads(path.read_text(encoding='utf-8-sig'))
            if record.get('schema') != 'video-subtitle-alignment/v1': raise ValueError('invalid alignment')
            identity = hashlib.sha256(('alignment\0' + source).encode()).hexdigest()[:24]
            register(identity, 'alignment', source, _hash_file(path), {'record': record}, root)
            report['alignment'] += 1
        except InterruptedError:
            raise
        except Exception as error:
            report['errors'].append({'source': source, 'kind': type(error).__name__})
    for path in ([] if visual_only else exchange.feedback_results()):
        source = path.relative_to(root).as_posix()
        try:
            if not path.resolve().is_relative_to(root): raise ValueError('source outside project')
            record = json.loads(path.read_text(encoding='utf-8-sig'))
            feedback_id = record.get('id')
            if not isinstance(feedback_id, str) or len(feedback_id) != 32 or any(c not in '0123456789abcdef' for c in feedback_id):
                raise ValueError('invalid feedback identity')
            identity = hashlib.sha256(('feedback\0' + feedback_id).encode()).hexdigest()[:24]
            register(identity, 'feedback', source, _hash_file(path), {'record': record}, root)
            report['feedback'] += 1
        except InterruptedError:
            raise
        except Exception as error:
            report['errors'].append({'source': source, 'kind': type(error).__name__})
    return report
