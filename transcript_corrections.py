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
    root = Path(root).resolve()
    path = root / 'transcript-corrections.json'
    if not path.resolve().is_relative_to(root): raise ValueError('修订记录位置无效')
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {'schemaVersion': 1, 'records': {}, 'annotations': []}


def save(state, root=HERE):
    target = Path(root) / 'transcript-corrections.json'
    temp = target.with_suffix('.json.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, target)


def lookup_record(state, source, row):
    """Find an existing overlay after relocation without changing historical IDs."""
    key = record_key(source, row)
    records = state.get('records', {})
    if key in records: return key, records[key]
    def suffix(value):
        import re
        parts = re.split(r'[\\/]+', str(value))
        positions = [i for i, part in enumerate(parts) if part.lower() == 'out']
        return tuple(part.casefold() for part in parts[positions[-1] + 1:]) if positions else ()
    expected = suffix(source)
    matches = []
    if expected:
        for old_key, record in records.items():
            try:
                if (suffix(record.get('sourceFile', '')) == expected and
                    record.get('file') == row['file'] and float(record['start']) == float(row['start']) and
                    float(record['end']) == float(row['end']) and normalize(record.get('original')) == normalize(row.get('text'))):
                    matches.append((old_key, record))
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
    if len(matches) > 1: raise CorrectionConflict('历史修订有多条匹配，请人工核对')
    return matches[0] if matches else (key, None)


def effective(row, source, state=None):
    state = load() if state is None else state
    _, record = lookup_record(state, source, row)
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
    from material_exchange import MaterialExchange
    source = MaterialExchange(root).transcript_source(source)
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
            key, record = lookup_record(state, source, raw)
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise ValueError('字幕缺少有效的录音定位') from error
        actual = hashlib.sha256(json.dumps(current, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if actual != expected_version:
            raise CorrectionConflict('字幕已发生变化，请刷新后重试')
        if normalize(current['text']) == replacement:
            return {'changed': False, 'revision': current.get('revision', 0)}
        records = state.setdefault('records', {})
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


def annotation_action(root, action, value=None):
    """Own annotation state transitions for external interfaces."""
    root = Path(root).resolve()
    value = value or {}
    if action == 'read':
        return load(root)
    with locked(root):
        state = load(root)
        notes = state.setdefault('annotations', [])
        records = state.setdefault('records', {})
        if action == 'add':
            from material_exchange import MaterialExchange
            source = MaterialExchange(root).transcript_source(value['source'])
            rows = []
            with source.open(encoding='utf-8') as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                        key, record = lookup_record(state, source, row)
                        if key == value['recordId'] and normalize(row.get('text')) == normalize(value['original']):
                            rows.append((row, record))
                    except (KeyError, TypeError, json.JSONDecodeError):
                        continue
            if len(rows) != 1: raise CorrectionConflict('原字幕无法唯一定位，请刷新')
            row, record = rows[0]
            text = normalize(record['text'] if record else row['text'])
            revision = record.get('revision', 0) if record else 0
            if text != normalize(value['text']) or revision != value['revision']:
                raise CorrectionConflict('正文已有新修订，请重新选择文字')
            start, length = value['selectionStartUtf16'], value['selectionLengthUtf16']
            if type(start) is not int or type(length) is not int or start < 0 or length < 1:
                raise ValueError('请选择文字并填写修改意见')
            raw = text.encode('utf-16-le')
            if (start + length) * 2 > len(raw): raise ValueError('选中文字超出范围')
            selected = raw[start*2:(start+length)*2].decode('utf-16-le')
            instruction = value['instruction'].strip()
            if not instruction: raise ValueError('请选择文字并填写修改意见')
            if record is None:
                record = {'id':value['recordId'],'sourceFile':str(source),'file':row['file'],'start':row['start'],'end':row['end'],'original':normalize(row['text']),'text':text,'revision':0}
                records[value['recordId']] = record
            note = {'id':uuid.uuid4().hex,'recordId':value['recordId'],'selected':selected,'selectionStartUtf16':start,'selectionLengthUtf16':length,'instruction':instruction,'replacement':normalize(value.get('replacement','')),'baseRevision':revision,'status':'draft','createdAt':datetime.datetime.now().astimezone().isoformat()}
            notes.append(note); result = note
        elif action == 'submit':
            if any(n.get('status') == 'submitted' for n in notes): raise ValueError('上一批仍在修订，请稍后再提交')
            pending = [n for n in notes if n.get('status') in ('draft','failed')]
            if not pending: raise ValueError('暂无待提交批注')
            result = uuid.uuid4().hex
            for note in pending: note.update(status='submitted',batchId=result,error='')
        elif action == 'remove':
            note = next((n for n in notes if n.get('id') == value['id']), None)
            if note and note.get('status') not in ('submitted','applied'): notes.remove(note)
            result = None
        elif action == 'edit':
            note = next((n for n in notes if n.get('id') == value['id']), None)
            if not note or note.get('status') in ('submitted','applied'): raise ValueError('这条批注不能再编辑')
            note.update(instruction=value['instruction'],replacement=normalize(value.get('replacement','')),status='draft',error=''); result = None
        elif action == 'fail':
            for note in notes:
                if note.get('batchId') == value['batch'] and note.get('status') == 'submitted': note.update(status='failed',error=str(value['error']))
            result = None
        else:
            raise ValueError('未知批注操作')
        save(state, root)
        return result


if __name__ == '__main__':
    import argparse, sys
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--annotation-action', required=True, choices=['read','add','submit','remove','edit','fail'])
    args = parser.parse_args()
    try:
        request = json.load(sys.stdin) if args.annotation_action != 'read' else {}
        print(json.dumps(annotation_action(args.root, args.annotation_action, request), ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError, UnicodeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
