"""Local material and feedback gateway for AI agents and APIs.

It turns the project's independently-produced transcripts, slide captures, OCR
and visual-analysis results into one provenance-preserving manifest.  It never
records, transcribes, uploads, edits notes, or listens on a network interface.
Feedback is stored separately and never applied to source materials or notes.
"""
from __future__ import annotations
from data_location import data_root as default_data_root
from material_snapshot import ManifestBuilder, build, iso, read_json, rel, read_content

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
    day = (query.get('day') or [''])[0]
    if day:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day): raise ValueError('invalid day')
        dt.date.fromisoformat(day)
        def item_day(item):
            record = item.get('data', {}).get('effectiveRecord', {})
            value = record.get('date') if isinstance(record, dict) else None
            if isinstance(value, str):
                try: return dt.date.fromisoformat(value).isoformat()
                except ValueError: pass
            source = item.get('source', '')
            matches = re.findall(r'(?:^|/)(?:cloud-asr-)?(\d{8})(?=/|$)', source)
            if matches:
                try: return dt.datetime.strptime(matches[-1], '%Y%m%d').date().isoformat()
                except ValueError: pass
            if item.get('observedAt'):
                try: return parsed_time(item['observedAt']).astimezone().date().isoformat()
                except (ValueError, OverflowError): pass
            return None
        items = [item for item in items if item_day(item) == day]
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
            indexed_content = re.fullmatch(r'/v1/indexed-materials/([0-9a-f]{24})/content', parsed.path)
            if indexed_content:
                from material_store import read_material
                try:
                    item, content = read_material(indexed_content.group(1), root)
                    if isinstance(content, dict):
                        self.reply(200, content)
                    else:
                        mime = mimetypes.guess_type(item['source'])[0] or 'application/octet-stream'
                        self.reply(200, content, mime)
                except FileNotFoundError:
                    self.reply(404, {'error': 'material unavailable'})
                except (ValueError, OSError, sqlite3.Error):
                    self.reply(503, {'error': 'material read failed'})
                return
            if parsed.path == '/v1/modules':
                from material_store import list_module_status
                try:
                    self.reply(200, {'items': list_module_status(root), 'meaning': 'last reported status; not a live heartbeat'})
                except (OSError, sqlite3.Error):
                    self.reply(503, {'error': 'material database unavailable'})
                return
            if parsed.path == '/v1/context/current':
                from context_auto import current
                self.reply(200, current(root))
                return
            if parsed.path == '/v1/visual/tasks':
                from visual_worker import list_tasks
                try:
                    self.reply(200, list_tasks(root))
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
            try:
                content, mime = read_content(root, item)
            except FileNotFoundError:
                self.reply(404, {'error': 'source unavailable'}); return
            except OSError:
                self.reply(503, {'error': 'material read failed'}); return
            self.reply(200, content, mime)

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
                from subtitle_service import correct, CorrectionConflict
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
                try:
                    result, warnings = correct(root, item, version, replacement)
                except CorrectionConflict as error:
                    self.reply(409, {'error': str(error)}); return
                except (ValueError, KeyError, TypeError) as error:
                    self.reply(400, {'error': str(error)}); return
                except OSError:
                    self.reply(503, {'error': '无法写入字幕修订'}); return
                if result['changed']:
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
    parser.add_argument("--root", type=Path, default=default_data_root())
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
    from gateway_credentials import load_or_create_gateway_token
    try:
        token = load_or_create_gateway_token(root)
    except ValueError as error:
        raise SystemExit(str(error))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(root, manifest, token))
    print(f"AI material gateway: http://127.0.0.1:{args.port}/v1/health", flush=True)
    try:
        if args.stop_file:
            server.timeout = .5
            while not args.stop_file.exists(): server.handle_request()
        else:
            server.serve_forever(poll_interval=0.5)
    finally: server.server_close()


if __name__ == "__main__":
    main()
