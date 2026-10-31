"""Correction overlays; original recording and JSONL files are never overwritten."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
import datetime
import shutil

HERE = Path(__file__).resolve().parent


class CorrectionConflict(ValueError):
    """The displayed subtitle no longer matches its current source or revision."""


def normalize(text):
    return str(text or '').replace('\r\n', '\n').replace('\r', '\n')


def record_key(source, row):
    def number(value):
        return f'{float(value):.3f}'.rstrip('0').rstrip('.') or '0'
    raw = '\n'.join([str(Path(source).resolve()).replace('/', '\\').lower(), str(row['file']),
                     number(row['start']), number(row['end'])])
    return hashlib.sha256(raw.encode()).hexdigest()


@contextlib.contextmanager
def locked(root=HERE):
    deadline = time.monotonic() + 5
    while True:
        handle = None
        try:
            handle = (Path(root) / '.transcript-corrections.lock').open('a+b')
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if handle: handle.close()
            if time.monotonic() >= deadline: raise
            time.sleep(.03)
    try:
        yield
    finally:
        handle.seek(0)
        if os.name == 'nt': msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def load(root=HERE):
    path = Path(root) / 'transcript-corrections.json'
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {'schemaVersion': 1, 'records': {}, 'annotations': []}


def save(state, root=HERE):
    target = Path(root) / 'transcript-corrections.json'
    temp = target.with_suffix('.json.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, target)


def effective(row, source, state=None):
    state = load() if state is None else state
    record = state.get('records', {}).get(record_key(source, row))
    if record and normalize(record['original']) == normalize(row.get('text')):
        return {**row, 'text': record['text'], 'revision': record['revision'], 'raw_text': row.get('text', '')}
    return row


def apply_replacements(text, annotations, replacements):
    raw = normalize(text).encode('utf-16-le')
    ordered = sorted(annotations, key=lambda note: note['selectionStartUtf16'])
    last = 0
    for note in ordered:
        start, size = note['selectionStartUtf16'], note['selectionLengthUtf16']
        if start < last or size < 1 or start * 2 + size * 2 > len(raw): raise ValueError('批注范围重叠或已变化，请重新选择')
        if raw[start*2:(start+size)*2].decode('utf-16-le') != note['selected']: raise ValueError('选中文字已变化，请重新核对')
        last = start + size
    for note in reversed(ordered):
        start, size = note['selectionStartUtf16'] * 2, note['selectionLengthUtf16'] * 2
        replacement = normalize(replacements[note['id']])
        if len(replacement) > 4000: raise ValueError('修订结果过长')
        raw = raw[:start] + replacement.encode('utf-16-le') + raw[start+size:]
    return raw.decode('utf-16-le')


def apply_manual_text(root, source, line_number, expected_version, replacement):
    """Commit an explicit whole-segment correction without changing the raw JSONL."""
    root = Path(root).resolve()
    source = Path(source).resolve()
    if not source.is_relative_to((root / 'out').resolve()) or source.name != 'timeline.jsonl':
        raise ValueError('修订来源超出录音项目')
    if not isinstance(line_number, int) or isinstance(line_number, bool) or line_number < 1:
        raise ValueError('无效字幕位置')
    if not isinstance(replacement, str) or not replacement.strip() or len(replacement) > 4000:
        raise ValueError('修订内容不能为空且不能超过4000字')
    replacement = normalize(replacement)
    with locked(root):
        with source.open(encoding='utf-8') as incoming:
            raw_line = next((line for index, line in enumerate(incoming, 1) if index == line_number), None)
        if raw_line is None:
            raise CorrectionConflict('原字幕已不存在，请刷新')
        raw = json.loads(raw_line)
        if not isinstance(raw, dict) or not isinstance(raw.get('text'), str):
            raise ValueError('原字幕格式无效')
        state = load(root)
        try:
            current = effective(raw, source, state)
            key = record_key(source, raw)
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise ValueError('字幕缺少有效的录音定位') from error
        actual = hashlib.sha256(json.dumps(current, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if actual != expected_version:
            raise CorrectionConflict('字幕已发生变化，请刷新后重试')
        if normalize(current['text']) == replacement:
            return {'changed': False, 'revision': current.get('revision', 0)}
        records = state.setdefault('records', {})
        record = records.get(key)
        if record is None:
            record = {'id': key, 'sourceFile': str(source), 'file': raw['file'], 'start': raw['start'], 'end': raw['end'],
                      'original': raw['text'], 'text': raw['text'], 'revision': 0}
            records[key] = record
        elif normalize(record.get('original')) != normalize(raw['text']):
            raise CorrectionConflict('原字幕已发生变化，请重新核对')
        previous = normalize(current['text'])
        revision = int(record.get('revision', 0))
        record['text'] = replacement
        record['revision'] = revision + 1
        stamp = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
        state.setdefault('annotations', []).append({
            'id': uuid.uuid4().hex, 'recordId': key, 'selected': previous,
            'selectionStartUtf16': 0, 'selectionLengthUtf16': len(previous.encode('utf-16-le')) // 2,
            'instruction': '用户直接修订整条字幕', 'replacement': replacement, 'baseRevision': revision,
            'status': 'applied', 'batchId': '', 'error': '', 'createdAt': stamp, 'appliedAt': stamp, 'evidence': None,
        })
        save(state, root)
    return {'changed': True, 'revision': revision + 1}


def publish_reviewed(source, root=HERE):
    source = Path(source)
    output = source.with_name('timeline.corrected.jsonl')
    temp = output.with_suffix('.jsonl.tmp')
    with locked(root):
        state = load(root)
        with source.open(encoding='utf-8') as incoming, temp.open('w', encoding='utf-8') as outgoing:
            for line in incoming:
                try: row = json.loads(line)
                except ValueError: continue
                outgoing.write(json.dumps(effective(row, source, state), ensure_ascii=False) + '\n')
        if output.exists():
            def digest(path):
                value = hashlib.sha256()
                with path.open('rb') as data:
                    for chunk in iter(lambda: data.read(1024 * 1024), b''):
                        value.update(chunk)
                return value.digest()
            if digest(output) == digest(temp):
                temp.unlink()
                return output
            backups = Path(root) / 'backups' / 'transcript-corrections'
            backups.mkdir(parents=True, exist_ok=True)
            backup = backups / (hashlib.sha256(str(source.resolve()).encode()).hexdigest()[:16] + '-' + uuid.uuid4().hex + '.jsonl')
            with output.open('rb') as previous, backup.open('xb') as saved:
                shutil.copyfileobj(previous, saved)
                saved.flush()
                os.fsync(saved.fileno())
            if digest(output) != digest(backup):
                raise OSError('existing corrected transcript changed during backup')
        os.replace(temp, output)
    return output
