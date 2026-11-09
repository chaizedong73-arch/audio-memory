"""Legacy material snapshot adapter; all filesystem discovery stays here."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import mimetypes
import re
import uuid
from pathlib import Path
from material_exchange import MaterialExchange

HERE = Path(__file__).resolve().parent
SCHEMA = "ai-material-gateway/v1"


def iso(timestamp: float | int | None) -> str | None:
    if not isinstance(timestamp, (int, float)) or timestamp <= 0:
        return None
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).isoformat().replace("+00:00", "Z")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(root: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError):
        return default


def source_time(record: dict) -> str | None:
    """Only absolute timestamps are unambiguous across time zones."""
    if isinstance(record.get('ts'), (int, float)) and record['ts'] > 0:
        try: return iso(record['ts'])
        except (OverflowError, OSError, ValueError): return None
    return None


class ManifestBuilder:
    def __init__(self, root: Path = HERE, exchange=None):
        self.root = root.resolve()
        self.exchange = exchange or MaterialExchange(self.root)
        self.materials: list[dict] = []
        self.warnings: list[dict] = []
        self._source_hashes: dict[Path, str] = {}

    def digest(self, path: Path) -> str:
        path = path.resolve()
        if path not in self._source_hashes:
            self._source_hashes[path] = file_hash(path)
        return self._source_hashes[path]

    def add(self, kind: str, path: Path, *, locator: str = "", observed_at: str | None = None,
            preview: str = "", data: dict | None = None, mime: str | None = None) -> None:
        path = path.resolve()
        relative = rel(self.root, path)
        if relative is None or not path.is_file():
            return
        source_hash = self.digest(path)
        version = json.dumps((data or {}).get('effectiveRecord'), ensure_ascii=False, sort_keys=True) if kind == 'transcript_segment' else ''
        # A line's identity is stable when its JSONL file is appended; content
        # revision is separate. Reordering lines still changes their identity.
        identity = f"{kind}\0{relative}\0{locator}" if kind == 'transcript_segment' else f"{kind}\0{relative}\0{locator}\0{source_hash}\0{version}"
        material_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        detected = mime or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.materials.append({
            "id": material_id, "kind": kind, "source": relative, "sourceHash": source_hash,
            "contentVersion": hashlib.sha256(version.encode()).hexdigest() if version else source_hash,
            "locator": locator or None, "observedAt": observed_at,
            "mime": detected, "preview": preview[:1200], "data": data or {},
        })

    def transcripts(self) -> None:
        from transcript_corrections import CorrectionConflict, effective, load
        corrections = load(self.root)
        for source, line_no, record, error in self.exchange.transcript_rows():
            if error:
                warning = {'source': source, 'code': error}
                if line_no: warning['line'] = line_no
                self.warnings.append(warning)
                continue
            if not isinstance(record, dict):
                self.warnings.append({'source': source, 'line': line_no, 'code': 'invalid_transcript_record'})
                continue
            path = self.root / source
            try: record = effective(record, path, corrections)
            except CorrectionConflict:
                self.warnings.append({'source': source, 'line': line_no, 'code': 'ambiguous_transcript_correction'})
                continue
            except (KeyError, ValueError, TypeError): pass
            text = str(record.get('text', '')).strip()
            if text:
                self.add('transcript_segment', path, locator=f'line:{line_no}', observed_at=source_time(record),
                         preview=text, data={**{k: record.get(k) for k in ('t', 'ts', 'start', 'end', 'file', 'model', 'revision', 'raw_text') if k in record}, 'effectiveRecord': record},
                         mime='application/json')

    def mobile_audio(self) -> None:
        for path in self.exchange.mobile_recordings():
            try:
                meta = read_json(path.parent / 'metadata.json', {}) or {}
                stamp = dt.datetime.fromisoformat(meta['startedAt'].replace('Z', '+00:00'))
                if stamp.tzinfo is None: raise ValueError('missing timezone')
                self.add('audio', path, observed_at=iso(stamp.timestamp()), preview='手机录音',
                         data={'mobileId':meta['id'],'deviceId':meta['deviceId'],'sha256':meta['sha256']}, mime='audio/wav')
            except (KeyError, ValueError, OSError):
                self.warnings.append({'source':rel(self.root,path),'code':'mobile_audio_unreadable'})

    def live_materials(self) -> None:
        for path in self.exchange.live_materials():
            self.add("live_transcript_digest", path, preview=path.read_text(encoding="utf-8")[:1200], mime="text/markdown")

    def slides(self) -> None:
        for index in self.exchange.visual_slide_indexes():
            document = read_json(index, {}) or {}
            for item in document.get("items", []):
                try: path = self.exchange.slide_file(str(item.get('path', '')), item.get('contentHash'))
                except (ValueError, OSError): continue
                self.add("ppt_slide", path, locator=str(item.get("id", "")), observed_at=iso(item.get("capturedAt")),
                         data={k: item.get(k) for k in ("firstSeenAt", "capturedAt", "lastSeenAt", "contentHash", "sourcePath", "videoSession", "videoOffsetSeconds") if k in item})
        for path in self.exchange.scene_frames():
            self.add("scene_frame", path, observed_at=iso(path.stat().st_mtime))

    def ocr_and_visual_results(self) -> None:
        try: catalog_path = self.exchange.ocr_catalog()
        except (ValueError, OSError):
            self.warnings.append({'code': 'invalid_ocr_catalog'})
            catalog_path = None
        catalog = (read_json(catalog_path, {}) or {}) if catalog_path else {}
        for source_path, entry in (catalog.get("pages", {}) or {}).items():
            if not isinstance(entry, dict): continue
            key = entry.get('hash')
            if not isinstance(key, str) or not re.fullmatch(r'[a-fA-F0-9]{1,64}', key): continue
            try: source = self.exchange.resolve_material(source_path, key)
            except (ValueError, OSError): continue
            folder = catalog_path.parent.resolve()
            result = (folder / (key + '.json')).resolve()
            if not folder.is_relative_to(self.root) or not result.is_relative_to(folder): continue
            payload = read_json(result, {}) or {}
            text = str(payload.get("text", "")).strip()
            if source.is_file() and text:
                self.add("ppt_ocr", source, locator=str(entry.get("hash", "")), observed_at=iso(source.stat().st_mtime), preview=text,
                         data={"terms": payload.get("terms", []), "extractor": "ppt_concepts", "ocrText": text}, mime="application/json")
        for path in self.exchange.visual_results():
            payload = read_json(path, {}) or {}
            data = {k: payload.get(k) for k in ("status", "model", "verification", "elapsedSeconds", "image") if k in payload} if path.name == 'last-analysis.json' else payload
            self.add("visual_analysis", path, preview=str(payload.get("text", payload.get("result", ""))), data=data)

    def build(self) -> dict:
        self.transcripts(); self.mobile_audio(); self.live_materials(); self.slides(); self.ocr_and_visual_results()
        self.materials.sort(key=lambda item: (item["observedAt"] or "", item["id"]), reverse=True)
        return {
            "schema": SCHEMA,
            "generatedAt": iso(dt.datetime.now(tz=dt.timezone.utc).timestamp()),
            "snapshotId": uuid.uuid4().hex,
            "scope": {"root": str(self.root), "network": "loopback-only", "writeAccess": False, "feedbackWriteAccess": True},
            "kinds": sorted({item["kind"] for item in self.materials}),
            "warnings": self.warnings,
            "materials": self.materials,
        }


def build(root: Path = HERE, write: bool = True) -> dict:
    manifest = ManifestBuilder(root).build()
    if write:
        destination = root / "out" / "ai-gateway" / "manifest.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(destination)
    return manifest




def read_content(root, item):
    """Read snapshot content after resolving its source inside the material root."""
    root = Path(root).resolve()
    path = (root / item['source']).resolve()
    if rel(root, path) is None or not path.is_file():
        raise FileNotFoundError('source unavailable')
    if item['kind'] == 'transcript_segment':
        if 'effectiveRecord' in item['data']:
            return item['data']['effectiveRecord'], 'application/json; charset=utf-8'
        try:
            line_no = int(str(item['locator']).split(':', 1)[1])
            with path.open(encoding='utf-8') as source:
                for current, line in enumerate(source, 1):
                    if current == line_no:
                        return json.loads(line), 'application/json; charset=utf-8'
        except (IndexError, OSError, ValueError, UnicodeDecodeError):
            pass
        raise FileNotFoundError('transcript segment unavailable')
    if item['kind'] == 'ppt_ocr':
        return {'text': item['data'].get('ocrText', item['preview']), 'data': item['data'], 'source': item['source']}, 'application/json; charset=utf-8'
    return path.read_bytes(), item['mime']


def workbench_snapshot(root, log, now):
    """Return bounded display data to the optional workbench interface."""
    import math
    from transcript_corrections import CorrectionConflict, load, lookup_record, normalize
    root = Path(root).resolve()
    exchange = MaterialExchange(root)
    if not re.fullmatch(r'(cloud-asr|recorder|transcriber|extract|annotation-worker)\.(stdout|stderr)\.log', log):
        raise ValueError('无效日志文件')
    def local(path):
        path = Path(path).resolve()
        if not path.is_relative_to(root): raise ValueError('资料来源不可用')
        return path
    def tail(path, limit):
        path = local(path)
        try:
            with path.open('rb') as stream:
                size = stream.seek(0, 2); offset = max(0, size-limit); stream.seek(offset)
                raw = stream.read()
            if offset: raw = raw.split(b'\n', 1)[-1]
            return raw.decode('utf-8', errors='replace')
        except FileNotFoundError: return ''
    def document(path):
        try: return read_json(local(path), {}) or {}
        except ValueError: return {}
    def number(value):
        try:
            result=float(value)
            return result if math.isfinite(result) else 0
        except (ValueError,TypeError): return 0
    def clock(value): return dt.datetime.fromtimestamp(value).strftime('%H:%M:%S')
    recordings = [Path(p) for p in exchange.recordings(('.wav',)) if Path(p).resolve().is_relative_to(root)]
    latest = max(recordings, key=lambda p:p.stat().st_mtime, default=None)
    last = latest.stat().st_mtime if latest else 0
    age = max(0,int(now-last)) if last else 0
    healthy = bool(last and now-last < 150)
    state = document(root/'cloud-asr-trial.json'); selected = document(root/'transcription-control.json')
    deadline=number(state.get('deadline')); legacy=bool(state.get('active') and deadline > now)
    mode=('cloud' if selected.get('mode')=='cloud' and number(selected.get('deadline'))>now else 'local') if selected else ('cloud' if legacy else 'local')
    active=legacy and mode=='cloud' and (not selected or selected.get('generation')==state.get('generation'))
    day=dt.datetime.fromtimestamp(now).strftime('%Y%m%d'); local_day=exchange.transcript_directory()/day
    timeline=local_day/'timeline.jsonl'; cloud=False
    if active and state.get('latestDayDir'):
        try:
            candidate=exchange.transcript_source(Path(state['latestDayDir'])/'timeline.jsonl')
            if candidate.is_file() and now-candidate.stat().st_mtime < 90: timeline=candidate;cloud=True
        except (ValueError,OSError,TypeError): pass
    corrections=load(root); rows=[]
    if timeline.is_file():
        for line in tail(timeline,128*1024).splitlines():
            try:
                row=json.loads(line)
                if isinstance(row,dict) and str(row.get('text','')).strip(): rows.append(row)
            except (ValueError,TypeError): pass
    rows=rows[-100:]; body=''; ranges=[]
    for row in rows:
        original=normalize(row.get('text'))
        try: key,record=lookup_record(corrections,timeline,row)
        except CorrectionConflict: raise
        except (KeyError,TypeError,ValueError,OverflowError): continue
        text=normalize(record.get('text')) if record and normalize(record.get('original'))==original else original
        revision=record.get('revision',0) if record and normalize(record.get('original'))==original else 0
        body+=str(row.get('t',''))+'   '; rendered=text.replace('\n','\r\n')
        start=len(body.encode('utf-16-le'))//2
        ranges.append({'Id':key,'Source':str(timeline),'File':str(row.get('file','')),'Original':original,'Text':text,'Start':number(row.get('start')),'End':number(row.get('end')),'Revision':revision,'DisplayStart':start,'DisplayLength':len(rendered.encode('utf-16-le'))//2})
        body+=rendered+'\r\n\r\n'
    trans_time=timeline.stat().st_mtime if timeline.is_file() else 0
    meta=('云端' if cloud else '本地')+' · 最近'+str(len(ranges))+'段'+(' · 更新 '+clock(trans_time) if trans_time else '')+(' · 时间为分片起点' if cloud else '')
    revised=sum(r['Revision']>0 for r in ranges)
    if revised: meta+=' · 已修订 '+str(revised)+'段'
    notices=[]
    if not healthy: notices.append('录音超过150秒未落盘，请查看录音错误日志')
    if active and not cloud: notices.append('云端尚无新结果或超过90秒未更新，当前显示本地转写')
    if not trans_time or now-trans_time>120: notices.append('转写暂未更新，可能正在等待内存或处理队列')
    if not active and state: notices.append('云端因连续网络失败停止，本地采集独立运行' if state.get('stopReason')=='consecutive_failures' else '云端试验已停止或已到期，本地采集独立运行')
    if active and state.get('recovering'): notices.append('云端网络异常，正在退避重试')
    model=str(state.get('model',''))
    model_label='豆包 2.0 Mini' if 'seed-2-0-mini' in model else '豆包 2.1 Lite' if 'seed-2-1-lite' in model else model or '云端 ASR'
    health='；'.join(notices) if notices else '录音与转写正在更新 · 云端成功 '+str(len(state.get('completed',[])))+'片 · 费用为估算，包含在途请求预留'
    record='正在采集' if healthy else '录音未更新'
    detail='最近落盘 '+clock(last)+' · '+str(age)+'秒前' if last else '尚无录音文件'
    latency=('接口 '+format(number(state.get('latestLatencySeconds')),'.2f')+'秒 · 15秒整片转写') if cloud else ('云端等待更新，显示本地材料' if active else '持续转写 · 云端试验未运行')
    cost='¥ '+format(number(state.get('estimatedYuan')),'.3f') if state else '未开始'
    deadline_text=(('试验至 ' if active else '原截止 ')+clock(deadline)+' · 估算停止线 ¥'+format(number(state.get('budgetYuan')),'g')) if deadline else '费用含请求预留，以账户账单为准'
    material=str(timeline) if timeline.is_file() else ''
    diagnostic='录音项目：'+str(root)+'\r\n'+record+' · '+detail+'\r\n'+(model_label if cloud else '本地 Whisper')+' · '+latency+'\r\n费用估算：'+cost+'；'+deadline_text+'\r\n'+health+'\r\n材料：'+material
    from context_auto import current
    context=current(root)
    return {'Root':str(root),'Recording':record,'RecordingDetail':detail,'RecordingHealthy':healthy,'Mode':mode,'Model':model_label if cloud else '本地 Whisper','Latency':latency,'Cost':cost,'Deadline':deadline_text,'Health':health,'Transcript':body or '尚未收到可识别的课堂语音。','TranscriptMeta':meta,'Memory':tail(local_day/'memory.md',128*1024) or '今天尚未生成记忆结果。','Log':re.sub(r'(?i)Bearer\s+[^\s"\']+','Bearer [已隐藏]',tail(root/log,48*1024)) or '这份日志暂无内容。','Diagnostic':diagnostic,'MaterialPath':material,'Ranges':ranges,'Annotations':corrections.get('annotations',[]),'SubtitleState':document(root/'subtitle-maintenance-state.json'),'SubtitleSettings':document(root/'subtitle-maintenance.json'),'NotesConfig':document(root/'notes-maintenance.json'),'NotesState':document(root/'notes-maintenance-state.json'),'Confirmations':document(root/'subtitle-confirmations.json'),'ContextState':context['state'],'ContextCandidate':context['candidate'] or {}}


if __name__ == '__main__':
    import argparse, sys
    parser=argparse.ArgumentParser();parser.add_argument('--workbench',action='store_true');parser.add_argument('--root',type=Path,required=True);parser.add_argument('--log',required=True);parser.add_argument('--now',type=float,required=True)
    args=parser.parse_args()
    try: print(json.dumps(workbench_snapshot(args.root,args.log,args.now),ensure_ascii=False))
    except (ValueError,OSError,KeyError,TypeError,OverflowError) as error:
        print(str(error),file=sys.stderr);sys.exit(1)
