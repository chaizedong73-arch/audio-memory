"""Local material and feedback gateway for AI agents and APIs.

It turns the project's independently-produced transcripts, slide captures, OCR
and visual-analysis results into one provenance-preserving manifest.  It never
records, transcribes, uploads, edits notes, or listens on a network interface.
Feedback is stored separately and never applied to source materials or notes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import mimetypes
import re
import secrets
import os
import sqlite3
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
GATEWAY_OUT = OUT / "ai-gateway"
SCHEMA = "ai-material-gateway/v1"
TEXT_TYPES = {"application/json", "text/markdown", "text/plain"}
MATERIAL_KINDS = {'transcript_segment', 'live_transcript_digest', 'ppt_slide', 'scene_frame', 'ppt_ocr', 'visual_analysis'}


def validate_action(value):
    """Validate agent requests before recording or executing them."""
    action = value.get('action')
    if action is None:
        return None  # Existing unstructured feedback remains readable.
    if action not in ('find_materials', 'check_materials', 'refresh_materials'):
        raise ValueError('unsupported action')
    params = value.get('params', {})
    if not isinstance(params, dict):
        raise ValueError('params must be an object')
    allowed = {'find_materials': {'kind', 'q', 'after', 'before', 'limit'},
               'check_materials': {'kinds', 'after', 'before'}, 'refresh_materials': set()}[action]
    if set(params) - allowed:
        raise ValueError('unsupported parameters')
    for key in ('kind', 'q', 'after', 'before'):
        if key in params and (not isinstance(params[key], str) or len(params[key]) > 500):
            raise ValueError(key + ' must be a string of at most 500 characters')
    if 'kind' in params and params['kind'] not in MATERIAL_KINDS:
        raise ValueError('unknown material kind')
    if 'limit' in params and (type(params['limit']) is not int or not 1 <= params['limit'] <= 100):
        raise ValueError('limit must be an integer from 1 to 100')
    if action == 'check_materials':
        kinds = params.get('kinds')
        if not isinstance(kinds, list) or not kinds or len(kinds) > len(MATERIAL_KINDS) or any(not isinstance(k, str) or k not in MATERIAL_KINDS for k in kinds) or len(set(kinds)) != len(kinds):
            raise ValueError('kinds must contain unique supported material types')
    # Reuse the gateway's date parser even when no materials exist.
    filtered({'materials': []}, {k: [params[k]] for k in ('after', 'before') if k in params})
    return action


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
    def __init__(self, root: Path = HERE):
        self.root = root.resolve()
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
        from transcript_corrections import effective, load
        corrections = load(self.root)
        for path in sorted((self.root / "out").glob("**/timeline.jsonl")):
            try:
                with path.open('rb') as source:
                    for line_no, raw in enumerate(source, 1):
                        try:
                            record = json.loads(raw.decode('utf-8'))
                            if not isinstance(record, dict): raise ValueError('record must be an object')
                        except (ValueError, UnicodeDecodeError):
                            self.warnings.append({'source': rel(self.root, path), 'line': line_no, 'code': 'invalid_transcript_record'})
                            continue
                        try: record = effective(record, path, corrections)
                        except (KeyError, ValueError, TypeError): pass
                        text = str(record.get("text", "")).strip()
                        if text:
                            self.add("transcript_segment", path, locator=f"line:{line_no}", observed_at=source_time(record),
                                     preview=text, data={**{k: record.get(k) for k in ("t", "ts", "start", "end", "file", "model", "revision", "raw_text") if k in record}, "effectiveRecord": record},
                                     mime="application/json")
            except OSError:
                self.warnings.append({'source': rel(self.root, path), 'code': 'transcript_unreadable'})
                continue

    def live_materials(self) -> None:
        for path in sorted((self.root / "out").glob("live-materials/**/当前课堂实时材料.md")):
            self.add("live_transcript_digest", path, preview=path.read_text(encoding="utf-8")[:1200], mime="text/markdown")

    def slides(self) -> None:
        out = self.root / "out"
        for index in sorted((out / "scene" / "ppt").glob("*/index.json")):
            document = read_json(index, {}) or {}
            for item in document.get("items", []):
                path = Path(str(item.get("path", "")))
                self.add("ppt_slide", path, locator=str(item.get("id", "")), observed_at=iso(item.get("capturedAt")),
                         data={k: item.get(k) for k in ("firstSeenAt", "capturedAt", "lastSeenAt", "contentHash", "sourcePath", "videoSession", "videoOffsetSeconds") if k in item})
        for path in sorted((out / "scene" / "frames").glob("*.png")):
            self.add("scene_frame", path, observed_at=iso(path.stat().st_mtime))

    def ocr_and_visual_results(self) -> None:
        out = self.root / "out"
        catalog = read_json(out / "ppt-concepts" / "catalog.json", {}) or {}
        for source_path, entry in (catalog.get("pages", {}) or {}).items():
            source = Path(source_path)
            result = out / "ppt-concepts" / f"{entry.get('hash', '')}.json"
            payload = read_json(result, {}) or {}
            text = str(payload.get("text", "")).strip()
            if source.is_file() and text:
                self.add("ppt_ocr", source, locator=str(entry.get("hash", "")), observed_at=iso(source.stat().st_mtime), preview=text,
                         data={"terms": payload.get("terms", []), "extractor": "ppt_concepts", "ocrText": text}, mime="application/json")
        for path in sorted((out / "scene").glob("last-analysis.json")):
            payload = read_json(path, {}) or {}
            self.add("visual_analysis", path, preview=str(payload.get("text", "")), data={k: payload.get(k) for k in ("status", "model", "verification", "elapsedSeconds", "image") if k in payload})
        for path in sorted((out / "visual-vocabulary" / "scene").glob("**/image.result.json")):
            payload = read_json(path, {}) or {}
            self.add("visual_analysis", path, preview=str(payload.get("text", payload.get("result", ""))), data=payload)

    def build(self) -> dict:
        self.transcripts(); self.live_materials(); self.slides(); self.ocr_and_visual_results()
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


def filtered(manifest: dict, query: dict[str, list[str]], *, apply_limit: bool = True) -> list[dict]:
    items = manifest["materials"]
    kind = (query.get("kind") or [None])[0]
    needle = (query.get("q") or [""])[0].lower()
    after = (query.get("after") or [""])[0]
    before = (query.get("before") or [""])[0]
    if kind: items = [item for item in items if item["kind"] == kind]
    variants = [needle] + [x.lower() for x in query.get('variant', []) if x]
    if needle: items = [item for item in items if any(v in (item["preview"] + json.dumps({k:v for k,v in item['data'].items() if k != 'effectiveRecord'}, ensure_ascii=False)).lower() for v in variants)]
    def parsed_time(value):
        parsed=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None: raise ValueError('时间必须带时区，例如 +08:00 或 Z')
        return parsed.astimezone(dt.timezone.utc)
    if after:
        boundary=parsed_time(after); items=[item for item in items if item['observedAt'] and parsed_time(item['observedAt']) >= boundary]
    if before:
        boundary=parsed_time(before); items=[item for item in items if item['observedAt'] and parsed_time(item['observedAt']) <= boundary]
    try: limit = min(max(int((query.get("limit") or ["100"])[0]), 1), 1000)
    except ValueError: limit = 100
    return items[:limit] if apply_limit else items


def handler(root: Path, manifest: dict | None = None, token: str | None = None):
    # Serving a stable snapshot keeps ordinary API requests fast and makes an
    # agent's citations reproducible.  `build` is the explicit refresh action.
    manifest = manifest if manifest is not None else build(root)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, code: int, value, mime="application/json; charset=utf-8"):
            raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(code); self.send_header("Content-Type", mime); self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store"); self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1")
            self.send_header("X-Content-Type-Options", "nosniff"); self.end_headers(); self.wfile.write(raw)

        def authorized(self):
            if token is None:
                return True
            provided = self.headers.get('Authorization', '')
            if hmac.compare_digest(provided.encode('utf-8'), ('Bearer ' + token).encode('ascii')):
                return True
            self.reply(401, {'error': 'valid local access token required'})
            return False

        def do_GET(self):
            host = self.headers.get('Host', '').lower().split(':', 1)[0]
            if host not in ('127.0.0.1', 'localhost'):
                self.reply(403, {'error': 'local host required'}); return
            if not self.authorized(): return
            parsed = urlparse(self.path); query = parse_qs(parsed.query)
            if parsed.path == "/v1/health":
                self.reply(200, {"ok": True, "schema": SCHEMA, "materials": len(manifest["materials"])})
                return
            if parsed.path == "/v1/manifest":
                self.reply(200, {k: v for k, v in manifest.items() if k != "materials"} | {"count": len(manifest["materials"])})
                return
            if parsed.path == '/v1/indexed-materials':
                from material_store import list_materials
                try:
                    limit = int((query.get('limit') or ['100'])[0]); offset = int((query.get('offset') or ['0'])[0])
                    data = list_materials(root, (query.get('kind') or [None])[0], limit, offset)
                    self.reply(200, {'schema': 'material-index/v1', **data})
                except ValueError as error:
                    self.reply(400, {'error': str(error)})
                except (OSError, sqlite3.Error):
                    self.reply(503, {'error': 'material database unavailable'})
                return
            if parsed.path == '/v1/modules':
                from material_store import list_module_status
                try:
                    self.reply(200, {'items': list_module_status(root), 'meaning': 'last reported status; not a live heartbeat'})
                except (OSError, sqlite3.Error):
                    self.reply(503, {'error': 'material database unavailable'})
                return
            if parsed.path == '/v1/context/current':
                folder = root / 'out' / 'context-auto'
                state = read_json(folder / 'state.json', {})
                candidate = read_json(folder / 'candidate.json')
                self.reply(200, {'schema': 'context-current/v1',
                                 'state': state if isinstance(state, dict) else {},
                                 'candidate': candidate if isinstance(candidate, dict) else None})
                return
            if parsed.path == '/v1/visual/tasks':
                folder = root / 'out' / 'visual-tasks'
                try:
                    paths = sorted(folder.glob('*.json'), key=lambda path: path.stat().st_mtime, reverse=True)[:100]
                    tasks = []
                    for path in paths:
                        if not path.resolve().is_relative_to(root.resolve()):
                            continue
                        state = read_json(path)
                        if isinstance(state, dict):
                            tasks.append({key: state[key] for key in ('source', 'stage', 'pages', 'error', 'warning', 'alignmentWarnings', 'indexWarning', 'gatewayWarning') if key in state})
                    self.reply(200, {'schema': 'visual-tasks/v1', 'items': tasks})
                except OSError:
                    self.reply(503, {'error': '视觉任务状态不可读取'})
                return
            if parsed.path == "/v1/feedback":
                try:
                    limit = min(max(int((query.get('limit') or ['100'])[0]), 1), 1000)
                except ValueError:
                    self.reply(400, {'error': 'invalid limit'}); return
                folder = root / 'out' / 'ai-gateway' / 'feedback'
                paths = sorted(folder.glob('*.json'), reverse=True)[:limit]
                self.reply(200, {'schema': 'ai-material-feedback/v1', 'items': [v for p in paths if (v := read_json(p)) is not None]})
                return
            match_feedback = re.fullmatch(r'/v1/feedback/([0-9a-f]{32})', parsed.path)
            if match_feedback:
                folder = root / 'out' / 'ai-gateway' / 'feedback'
                paths = list(folder.glob('*_' + match_feedback.group(1) + '.json'))
                record = read_json(paths[0]) if paths else None
                self.reply(200 if record else 404, record or {'error': 'feedback not found'}); return
            if parsed.path == "/v1/notes/subtitles":
                from notes_maintenance import collect
                try:
                    since = float((query.get('since') or ['0'])[0])
                    limit = min(max(int((query.get('limit') or ['100'])[0]), 1), 1000)
                    rows = collect(root, since, {}, limit=limit, require_review=True)
                    self.reply(200, {'schema':'reviewed-subtitles/v1','items':rows,'scope':'screened-only','count':len(rows)})
                except (ValueError, OSError, KeyError) as error:
                    self.reply(400, {'error':str(error)})
                return
            if parsed.path == "/v1/materials":
                snapshot = manifest
                try:
                    offset = int((query.get('offset') or ['0'])[0])
                    if offset < 0: raise ValueError('offset must be non-negative')
                    limit = min(max(int((query.get('limit') or ['100'])[0]), 1), 1000)
                    requested = (query.get('snapshot') or [None])[0]
                    if requested and requested != snapshot['snapshotId']:
                        self.reply(409, {'error': 'snapshot changed; restart pagination'}); return
                    items = filtered(snapshot, query, apply_limit=False)
                    page = items[offset:offset + limit]
                    self.reply(200, {'schema': SCHEMA, 'items': page, 'total': len(items), 'snapshot': snapshot['snapshotId'],
                                     'nextOffset': offset + len(page) if offset + len(page) < len(items) else None})
                except ValueError as error: self.reply(400, {'error': str(error)})
                return
            match = re.fullmatch(r"/v1/materials/([0-9a-f]{24})(?:/(content))?", parsed.path)
            if not match:
                self.reply(404, {"error": "unknown endpoint"}); return
            item = next((item for item in manifest["materials"] if item["id"] == match.group(1)), None)
            if item is None:
                self.reply(404, {"error": "material not found"}); return
            if not match.group(2):
                self.reply(200, item); return
            path = (root / item["source"]).resolve()
            if rel(root, path) is None or not path.is_file():
                self.reply(404, {"error": "source unavailable"}); return
            if item["kind"] == "transcript_segment":
                if 'effectiveRecord' in item['data']:
                    self.reply(200, item['data']['effectiveRecord']); return
                try:
                    line_no = int(str(item["locator"]).split(":", 1)[1])
                    with path.open(encoding="utf-8") as source:
                        for current, line in enumerate(source, 1):
                            if current == line_no:
                                self.reply(200, json.loads(line)); return
                except (IndexError, OSError, ValueError, UnicodeDecodeError):
                    self.reply(404, {"error": "transcript segment unavailable"}); return
            if item["kind"] == "ppt_ocr":
                self.reply(200, {"text": item["data"].get("ocrText", item["preview"]), "data": item["data"], "source": item["source"]}); return
            raw = path.read_bytes()
            self.reply(200, raw, item["mime"])

        def do_POST(self):
            nonlocal manifest
            # Browsers may otherwise cause local writes from an unrelated web page.
            if self.headers.get('Origin') is not None:
                self.reply(403, {'error': 'browser origins are not supported'}); return
            host = self.headers.get('Host', '').lower().split(':', 1)[0]
            if host not in ('127.0.0.1', 'localhost'):
                self.reply(403, {'error': 'local host required'}); return
            if not self.authorized(): return
            if self.headers.get_content_type() != 'application/json':
                self.reply(415, {'error': 'application/json required'}); return
            try:
                size = int(self.headers.get('Content-Length', ''))
            except ValueError:
                self.reply(411, {'error': 'Content-Length required'}); return
            if size < 0 or size > 65536:
                self.reply(413, {'error': 'body exceeds 65536 bytes'}); return
            try:
                value = json.loads(self.rfile.read(size).decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                self.reply(400, {'error': 'invalid JSON'}); return
            if not isinstance(value, dict):
                self.reply(400, {'error': 'JSON object required'}); return
            path = urlparse(self.path).path
            if path == '/v1/refresh':
                manifest = build(root, write=False)
                self.reply(200, {'ok': True, 'generatedAt': manifest['generatedAt'], 'materials': len(manifest['materials'])}); return
            if path == '/v1/transcripts/correct':
                from transcript_corrections import apply_manual_text, publish_reviewed, CorrectionConflict
                item_id, snapshot, version, replacement = (value.get(k) for k in ('id', 'snapshot', 'contentVersion', 'text'))
                if (not isinstance(item_id, str) or not re.fullmatch(r'[0-9a-f]{24}', item_id)
                        or not isinstance(snapshot, str) or not re.fullmatch(r'[0-9a-f]{32}', snapshot)
                        or not isinstance(version, str) or not re.fullmatch(r'[0-9a-f]{64}', version)
                        or not isinstance(replacement, str)):
                    self.reply(400, {'error': 'invalid correction request'}); return
                if snapshot != manifest['snapshotId']:
                    self.reply(409, {'error': '字幕快照已变化，请刷新后重试'}); return
                item = next((entry for entry in manifest['materials'] if entry['id'] == item_id and entry['kind'] == 'transcript_segment'), None)
                if not item:
                    self.reply(404, {'error': '字幕不存在'}); return
                location = re.fullmatch(r'line:([1-9][0-9]*)', str(item.get('locator') or ''))
                if not location:
                    self.reply(400, {'error': '字幕位置无效'}); return
                source = (root / item['source']).resolve()
                try:
                    result = apply_manual_text(root, source, int(location.group(1)), version, replacement)
                except CorrectionConflict as error:
                    self.reply(409, {'error': str(error)}); return
                except (ValueError, KeyError, TypeError) as error:
                    self.reply(400, {'error': str(error)}); return
                except OSError:
                    self.reply(503, {'error': '无法写入字幕修订'}); return
                warnings = []
                if result['changed']:
                    try:
                        publish_reviewed(source, root)
                    except (OSError, ValueError, KeyError, TypeError):
                        warnings.append('修订已保存，但修订稿刷新失败')
                    try:
                        from classroom_materials import publish
                        publish(source.parent, root=root)
                    except (OSError, ValueError, KeyError, TypeError):
                        warnings.append('修订已保存，但课堂材料刷新失败')
                    try:
                        manifest = build(root, write=False)
                    except (OSError, ValueError, KeyError, TypeError):
                        warnings.append('修订已保存，但网关索引刷新失败')
                self.reply(200, {'ok': True, **result, 'warnings': warnings}); return
            if path != '/v1/feedback':
                self.reply(404, {'error': 'unknown endpoint'}); return
            try:
                action = validate_action(value)
            except (TypeError, ValueError) as exc:
                self.reply(400, {'error': str(exc)}); return
            feedback_id = uuid.uuid4().hex
            received = dt.datetime.now(dt.timezone.utc)
            record = {'schema': 'ai-material-feedback/v1', 'id': feedback_id, 'receivedAt': iso(received.timestamp()), 'feedback': value,
                      'status': 'processing' if action else 'received'}
            folder = root / 'out' / 'ai-gateway' / 'feedback'
            temporary = None
            try:
                folder.mkdir(parents=True, exist_ok=True)
                filename = received.strftime('%Y%m%dT%H%M%S%fZ_') + feedback_id + '.json'
                destination = folder / filename
                def persist():
                    nonlocal temporary
                    temporary = folder / (filename + '.' + uuid.uuid4().hex + '.tmp')
                    with temporary.open('x', encoding='utf-8') as output:
                        json.dump(record, output, ensure_ascii=False)
                    temporary.replace(destination)
                persist()
            except OSError:
                if temporary is not None:
                    try: temporary.unlink(missing_ok=True)
                    except OSError: pass
                self.reply(500, {'error': 'unable to save feedback'}); return
            if action:
                try:
                    manifest = build(root, write=False)
                    params = value.get('params', {})
                    if action == 'refresh_materials':
                        result = {'generatedAt': manifest['generatedAt'], 'count': len(manifest['materials'])}
                    elif action == 'find_materials':
                        query = {k: [str(v)] for k, v in params.items()}
                        items = filtered(manifest, query)
                        result = {'items': items, 'count': len(items), 'generatedAt': manifest['generatedAt']}
                    else:
                        base = {k: [params[k]] for k in ('after', 'before') if k in params}
                        result = {'availability': {kind: bool(filtered(manifest, {**base, 'kind': [kind], 'limit': ['1']})) for kind in params['kinds']},
                                  'generatedAt': manifest['generatedAt']}
                    record.update(status='completed', result=result)
                except Exception as exc:
                    record.update(status='failed', error={'type': type(exc).__name__, 'message': 'automatic processing failed'})
                try:
                    persist()
                except OSError:
                    if temporary is not None:
                        try: temporary.unlink(missing_ok=True)
                        except OSError: pass
                    self.reply(500, {'error': 'unable to save processing result', 'id': feedback_id}); return
            self.reply(201, record)
    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Local AI material and feedback gateway")
    parser.add_argument("command", choices=("build", "serve", "show"), nargs="?", default="build")
    parser.add_argument("--root", type=Path, default=HERE)
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument('--stop-file', type=Path)
    parser.add_argument("--kind")
    parser.add_argument("--q")
    args = parser.parse_args()
    if args.command == "build":
        manifest = build(args.root); print(json.dumps({"manifest": str(args.root / "out" / "ai-gateway" / "manifest.json"), "materials": len(manifest["materials"])}, ensure_ascii=False)); return
    if args.command == "show":
        items = filtered(build(args.root, write=False), {k: [v] for k, v in {"kind": args.kind, "q": args.q}.items() if v})
        print(json.dumps(items, ensure_ascii=False, indent=2)); return
    root = args.root.resolve()
    manifest = build(root)
    token_dir = root / 'out' / 'ai-gateway'
    token_dir.mkdir(parents=True, exist_ok=True)
    token_path = token_dir / 'access-token'
    try:
        fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        token = token_path.read_text(encoding='ascii').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', token):
            raise SystemExit('Invalid gateway token file; inspect it before starting.')
    else:
        token = secrets.token_urlsafe(32)
        with os.fdopen(fd, 'w', encoding='ascii') as output:
            output.write(token)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(root, manifest, token))
    print(f"AI material gateway: http://127.0.0.1:{args.port}/v1/health", flush=True)
    print(f"Local access token file: {token_path}", flush=True)
    try:
        if args.stop_file:
            server.timeout = .5
            while not args.stop_file.exists(): server.handle_request()
        else:
            server.serve_forever(poll_interval=0.5)
    finally: server.server_close()


if __name__ == "__main__":
    main()
