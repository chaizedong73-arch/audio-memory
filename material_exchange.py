"""Storage-facing contract for recording producers and transcription consumers."""
import json
from pathlib import Path
import re
import datetime as dt
import hashlib
import math
import threading

_MOBILE_LOCK = threading.Lock()


class MaterialExchange:
    def __init__(self, root, *, recordings=None, transcripts=None):
        root = Path(root).resolve()
        self._root = root
        self._recordings = Path(recordings).resolve() if recordings is not None else root / 'record'
        self._transcripts = Path(transcripts).resolve() if transcripts is not None else root / 'out'

    def recording_directory(self):
        return self._recordings

    def transcript_directory(self):
        return self._transcripts

    def recordings(self, extensions=('.wav', '.flac')):
        return sorted(str(path) for path in self._recordings.iterdir()
                      if path.is_file() and path.suffix.lower() in extensions) if self._recordings.is_dir() else []

    def mobile_sources(self, device_id, material_id):
        for value in (device_id, material_id):
            if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value): raise ValueError('invalid identity')
        folder = (self._transcripts / 'mobile-sync' / device_id / material_id).resolve()
        if not folder.is_relative_to(self._root): raise ValueError('mobile source outside data root')
        return folder / 'audio.wav', folder / 'timeline.jsonl'

    def ingest_audio_sources(self):
        local = [Path(path) for path in self.recordings(('.wav',))]
        mobile = self.mobile_recordings()
        return sorted(local + mobile)

    def mobile_recordings(self):
        return [p for p in self._inside_files((self._transcripts / 'mobile-sync').glob('*/*/audio.wav'))
                if (p.parent / 'metadata.json').resolve().is_relative_to(self._root)]

    def _inside_files(self, paths):
        return sorted(p for p in paths if p.resolve().is_relative_to(self._root) and p.is_file())

    def live_materials(self):
        return self._inside_files(self._transcripts.glob('live-materials/**/当前课堂实时材料.md'))

    def scene_frames(self):
        return self._inside_files((self._transcripts / 'scene' / 'frames').glob('*.png'))

    def visual_results(self):
        return self._inside_files((self._transcripts / 'scene').glob('last-analysis.json')) + self._inside_files((self._transcripts / 'visual-vocabulary' / 'scene').glob('**/image.result.json'))

    def audio_for_stem(self, stem):
        if not isinstance(stem, str) or not stem or Path(stem).name != stem or stem in ('.', '..'):
            raise ValueError('无效录音定位')
        source = (self._recordings / (stem + '.wav')).resolve()
        if not source.is_relative_to(self._recordings.resolve()) or not source.is_relative_to(self._root):
            raise ValueError('无效录音定位')
        return source if source.is_file() else None

    def videos(self):
        folder = self._recordings / 'camera'
        if not folder.is_dir(): return []
        return sorted(path for path in folder.iterdir()
                      if path.is_file() and path.suffix.lower() in {'.webm', '.mp4', '.mov', '.mkv'}
                      and '.partial.' not in path.name.lower())

    def video_source(self, video):
        video = Path(video).resolve(strict=True)
        camera = (self._recordings / 'camera').resolve()
        if not video.is_file() or not video.is_relative_to(camera) or not video.is_relative_to(self._root) or '.partial.' in video.name.lower():
            raise ValueError('Expected a completed local camera video')
        return video, video.relative_to(self._root).as_posix()

    def append_transcripts(self, day, rows, *, cloud=False):
        if not re.fullmatch(r'[0-9]{8}', day):
            raise ValueError('invalid recording day')
        folder = self._transcripts / (('cloud-asr-' if cloud else '') + day)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / 'timeline.jsonl'
        with target.open('a', encoding='utf-8') as output:
            for row in rows:
                output.write(json.dumps(row, ensure_ascii=False) + '\n')
        return folder

    def transcript_source(self, value, *, allow_relocated=False):
        source = Path(value).resolve()
        allowed = self._transcripts.resolve()
        if source.is_relative_to(allowed) and source.is_relative_to(self._root) and source.name == 'timeline.jsonl':
            return source
        # Historical records stored absolute paths. Only rebind the portion under
        # the old out directory to an existing file in this data root.
        parts = re.split(r'[\\/]+', str(value)) if allow_relocated else []
        positions = [i for i, part in enumerate(parts) if part.lower() == 'out']
        if positions:
            suffix = parts[positions[-1] + 1:]
            if suffix and all(part not in ('', '.', '..') for part in suffix):
                source = allowed.joinpath(*suffix).resolve()
                if (source.is_relative_to(allowed) and source.is_relative_to(self._root)
                        and source.name == 'timeline.jsonl' and source.is_file()):
                    return source
        raise ValueError('字幕来源超出录音项目')

    def transcript_fingerprint(self):
        sources = []
        for path in sorted(self._transcripts.glob('**/timeline.jsonl')):
            try:
                if path.resolve().is_relative_to(self._root):
                    stat = path.stat()
                    sources.append((path.relative_to(self._root).as_posix(), stat.st_size, stat.st_mtime_ns))
            except OSError:
                continue
        return sources

    def transcript_rows(self, stop_file=None, paths=None):
        for path in (sorted(self._transcripts.glob('**/timeline.jsonl')) if paths is None else paths):
            if stop_file and Path(stop_file).exists(): raise InterruptedError('alignment stopped')
            try: source = path.relative_to(self._root).as_posix()
            except ValueError:
                yield path.name, 0, None, 'transcript_source_outside_project'
                continue
            if not path.resolve().is_relative_to(self._root):
                yield source, 0, None, 'transcript_source_outside_project'
                continue
            try:
                with path.open('rb') as stream:
                    for line, raw in enumerate(stream, 1):
                        if stop_file and Path(stop_file).exists(): raise InterruptedError('alignment stopped')
                        try:
                            row = json.loads(raw.decode('utf-8'))
                        except (ValueError, UnicodeDecodeError):
                            yield source, line, None, 'invalid_transcript_record'
                        else:
                            yield source, line, row, None
            except OSError:
                yield source, 0, None, 'transcript_unreadable'

    def recent_transcripts(self, days):
        """Yield corrected rows from requested calendar days in compatibility order."""
        from transcript_corrections import CorrectionConflict, effective, load
        paths = []
        for day in sorted(days):
            if not re.fullmatch(r'[0-9]{8}', day): raise ValueError('invalid transcript day')
            paths.append(self._transcripts / day / 'timeline.jsonl')
            paths.append(self._transcripts / ('cloud-asr-' + day) / 'timeline.jsonl')
            paths.extend(self._transcripts.glob('cloud-asr-*/' + day + '/timeline.jsonl'))
        corrections = load(self._root)
        for path in sorted(paths, key=lambda p: (p.relative_to(self._transcripts).parts[0].startswith('cloud-asr-'), p.stat().st_mtime if p.exists() else 0)):
            if not path.exists(): continue
            if not path.resolve().is_relative_to(self._root): continue
            source = path.relative_to(self._root).as_posix()
            with path.open(encoding='utf-8') as stream:
                for line, text in enumerate(stream, 1):
                    try:
                        row = json.loads(text)
                        if not isinstance(row, dict): continue
                        try: row = effective(row, path, corrections)
                        except CorrectionConflict: raise
                        except (KeyError, TypeError, ValueError, OverflowError): pass
                        yield source, line, row
                    except CorrectionConflict:
                        raise
                    except (ValueError, TypeError):
                        continue

    @staticmethod
    def classroom_session_id(value):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
            raise ValueError('课堂会话标识无效')
        return value

    def classroom_package(self):
        """Resolve the current session inside this data root, including moved data."""
        folder = (self._transcripts / 'classroom-bridge').resolve()
        if not folder.is_relative_to(self._root): raise ValueError('课堂包位置无效')
        latest_file = (folder / 'latest.json').resolve()
        if not latest_file.is_relative_to(folder): raise ValueError('课堂包位置无效')
        latest = json.loads(latest_file.read_text(encoding='utf-8'))
        if latest.get('status') != 'ready_for_notes': raise ValueError('没有就绪的课堂材料包')
        session = self.classroom_session_id(latest.get('sessionId'))
        path = (folder / session / 'notes-input.json').resolve()
        if not path.is_relative_to(folder) or not path.is_file(): raise ValueError('课堂材料包不存在')
        package = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(package, dict): raise ValueError('课堂材料包格式无效')
        if 'video' in package and (not isinstance(package['video'], dict) or package['video'].get('id') != session):
            raise ValueError('课堂会话标识不一致')
        return path, package

    def recorded_video(self, value):
        video = Path(value).resolve(strict=True)
        if not video.is_file() or not video.is_relative_to(self._recordings.resolve()) or not video.is_relative_to(self._root):
            raise ValueError('录像来源无效')
        return video

    def session_transcripts(self, start, end):
        rows, sources = [], []
        for timeline in self._transcripts.glob('**/timeline.jsonl'):
            if not timeline.resolve().is_relative_to(self._root): continue
            picked = []
            try:
                for line_no, line in enumerate(timeline.read_text(encoding='utf-8').splitlines(), 1):
                    row = json.loads(line); ts = float(row.get('ts', -1))
                    if start <= ts <= end and row.get('text', '').strip(): picked.append({'line': line_no, **row})
                if picked:
                    digest = hashlib.sha256()
                    with timeline.open('rb') as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
                    rows.extend(picked)
                    sources.append({'path': str(timeline.resolve()), 'hash': digest.hexdigest(), 'count': len(picked)})
            except (OSError, ValueError):
                continue
        return rows, sources

    def video_start(self, video):
        events = self._transcripts / 'scene' / 'events.jsonl'
        if not events.is_file() or not events.resolve().is_relative_to(self._root): return None
        found = None
        try:
            with events.open('rb') as stream:
                for raw in stream:
                    try:
                        event = json.loads(raw.decode('utf-8'))
                        ts = event.get('startAt')
                        if (event.get('event') == 'record-end' and event.get('state') == 'saved'
                                and isinstance(ts, (int, float)) and math.isfinite(ts) and ts > 0
                                and Path(event.get('path', '')).resolve() == video): found = ts
                    except (ValueError, TypeError, AttributeError, OSError, UnicodeDecodeError):
                        continue
        except OSError:
            return None
        return found

    def video_index(self, value):
        path = Path(value).resolve(strict=True)
        if not path.is_file() or not path.is_relative_to(self._root): raise ValueError('invalid index')
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        return path, data

    def video_slide_index(self, value):
        path, data = self.video_index(value)
        images = [str(Path(item['path']).resolve()) for item in data.get('items', [])]
        if any(not Path(image).is_relative_to(self._root) for image in images): raise ValueError('image outside project')
        return path, images, path.parent / 'video.json'

    def validate_visual_root(self):
        if not self._transcripts.is_relative_to(self._root):
            raise ValueError('visual storage outside data root')

    def recording_receipt(self):
        self.validate_visual_root()
        path = self._transcripts / 'scene' / 'last-recording.json'
        if not path.resolve().is_relative_to(self._root): raise ValueError('recording receipt outside data root')
        try: return json.loads(path.read_text(encoding='utf-8-sig'))
        except FileNotFoundError: return {}

    def slide_catalog(self):
        pages, errors = [], []
        for index in (self._transcripts / 'scene' / 'ppt').glob('*/index.json'):
            try:
                if not index.resolve().is_relative_to(self._root): raise ValueError('index outside data root')
                try: document = json.loads(index.read_text(encoding='utf-8-sig'))
                except FileNotFoundError: document = {}
                pages.extend(document.get('items', []))
            except (ValueError, OSError):
                errors.append('invalid_slide_index')
        return pages, errors

    def resolve_material(self, value, expected_hash=None):
        """Resolve a local material, rebinding old paths only with matching SHA-256."""
        candidate = Path(value)
        candidate = (candidate if candidate.is_absolute() else self._root / candidate).resolve()
        if candidate.is_relative_to(self._root) and candidate.is_file(): return candidate
        if not isinstance(expected_hash, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', expected_hash):
            raise ValueError('资料来源不可安全定位')
        parts = re.split(r'[\\/]+', str(value))
        positions = [i for i, part in enumerate(parts) if part.lower() in ('out', 'record')]
        if not positions: raise ValueError('资料来源不可安全定位')
        suffix = parts[positions[-1] + 1:]
        if not suffix or any(part in ('', '.', '..') for part in suffix): raise ValueError('资料来源不可安全定位')
        base = self._transcripts if parts[positions[-1]].lower() == 'out' else self._recordings
        candidate = base.joinpath(*suffix).resolve()
        if not candidate.is_relative_to(self._root) or not candidate.is_file(): raise ValueError('资料来源不可安全定位')
        digest = hashlib.sha256()
        with candidate.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
        if digest.hexdigest().lower() != expected_hash.lower(): raise ValueError('迁移资料哈希不一致')
        return candidate

    def slide_file(self, value, expected_hash=None):
        path = self.resolve_material(value, expected_hash)
        folder = (self._transcripts / 'scene' / 'ppt').resolve()
        if not path.is_relative_to(folder): raise ValueError('录像PPT页面不可用')
        return path

    def visual_slide_indexes(self):
        return self._inside_files((self._transcripts / 'scene' / 'ppt').glob('*/index.json'))

    def ocr_catalog(self):
        path = self._transcripts / 'ppt-concepts' / 'catalog.json'
        if not path.resolve().is_relative_to(self._root): raise ValueError('OCR catalog outside data root')
        return path

    def alignment_results(self):
        return sorted((self._transcripts / 'alignments').glob('*.json'))

    def feedback_results(self):
        return sorted((self._transcripts / 'ai-gateway' / 'feedback').glob('*.json'))

    def import_mobile(self, meta, audio, start, revision, duration):
        """Publish a validated phone package without overwriting different audio."""
        for key in ('id', 'deviceId'):
            if not isinstance(meta.get(key), str) or not re.fullmatch(r'[a-f0-9]{32}', meta[key]):
                raise ValueError('invalid identity')
        if hashlib.sha256(audio).hexdigest() != meta.get('sha256'):
            raise ValueError('audio hash mismatch')
        folder = self._transcripts / 'mobile-sync' / meta['deviceId'] / meta['id']
        if not folder.resolve().is_relative_to(self._root):
            raise ValueError('destination outside data root')
        with _MOBILE_LOCK:
            current = folder / 'metadata.json'
            audio_path = folder / 'audio.wav'
            if audio_path.exists():
                digest = hashlib.sha256()
                with audio_path.open('rb') as existing:
                    for block in iter(lambda: existing.read(1024 * 1024), b''):
                        digest.update(block)
                if digest.hexdigest() != meta['sha256']:
                    raise FileExistsError('stored audio differs from supplied audio')
            if current.exists():
                old = json.loads(current.read_text(encoding='utf-8'))
                if old['sha256'] != meta['sha256']: raise FileExistsError('identity has different audio')
                old_revision = dt.datetime.fromisoformat(old['updatedAt'].replace('Z', '+00:00'))
                if revision < old_revision: raise FileExistsError('newer version already stored')
                if revision == old_revision:
                    if old != meta: raise FileExistsError('same version has different metadata')
                    return {'status': 'saved', 'id': meta['id'], 'duplicate': True}
            folder.mkdir(parents=True, exist_ok=True)
            if not audio_path.exists():
                temporary = folder / 'audio.wav.tmp'; temporary.write_bytes(audio); temporary.replace(audio_path)
            row = {'text': meta.get('text', ''), 'ts': start.timestamp(), 't': start.strftime('%H:%M:%S'),
                   'date': start.date().isoformat(), 'start': 0, 'end': duration,
                   'file': audio_path.relative_to(self._root).as_posix(),
                   'model': str(meta.get('model', 'mobile-recording'))[:150],
                   'mobileId': meta['id'], 'deviceId': meta['deviceId']}
            temporary = folder / 'timeline.jsonl.tmp'
            temporary.write_text(json.dumps(row, ensure_ascii=False) + '\n', encoding='utf-8')
            temporary.replace(folder / 'timeline.jsonl')
            temporary = current.with_name(current.name + '.tmp')
            temporary.write_text(json.dumps(meta, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            temporary.replace(current)
        return {'status': 'saved', 'id': meta['id'], 'duplicate': False}
