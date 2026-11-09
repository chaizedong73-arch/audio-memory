"""Opt-in pinned HTTPS receiver; the existing AI gateway stays loopback-only."""
from data_location import data_root as default_data_root
from gateway_credentials import read_gateway_token
from material_exchange import MaterialExchange
import argparse
import base64
import datetime as dt
import hashlib
import hmac
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import threading
import urllib.request
import wave
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_PACKAGE = 8 * 1024 * 1024
ID = re.compile(r'^[a-f0-9]{32}$')


def atomic(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def import_package(root, data):
    root = Path(root)
    if len(data) > MAX_PACKAGE: raise ValueError('package too large')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) != 2 or {e.filename for e in entries} != {'metadata.json', 'audio.wav'}:
            raise ValueError('expected metadata.json and audio.wav')
        if any(e.file_size > MAX_PACKAGE for e in entries) or sum(e.file_size for e in entries) > MAX_PACKAGE:
            raise ValueError('expanded package too large')
        raw_meta = archive.read('metadata.json')
        if len(raw_meta) > 256 * 1024: raise ValueError('metadata too large')
        meta = json.loads(raw_meta)
        audio = archive.read('audio.wav')
    if not isinstance(meta, dict): raise ValueError('invalid metadata')
    if set(meta) - {'id','deviceId','startedAt','updatedAt','sha256','text','model','duration','usage'}: raise ValueError('unknown metadata fields')
    if 'usage' in meta and (not isinstance(meta['usage'],list) or len(meta['usage'])>500): raise ValueError('invalid usage records')
    for key in ('id', 'deviceId'):
        if not isinstance(meta.get(key), str) or not ID.fullmatch(meta[key]): raise ValueError('invalid identity')
    stamp = meta.get('startedAt')
    updated = meta.get('updatedAt')
    if not isinstance(stamp, str) or not isinstance(updated, str): raise ValueError('missing timestamps')
    start = dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    revision = dt.datetime.fromisoformat(updated.replace('Z', '+00:00'))
    if start.tzinfo is None or revision.tzinfo is None: raise ValueError('timestamps require timezone')
    text = meta.get('text', '')
    if not isinstance(text, str) or len(text) > 40000: raise ValueError('invalid transcript')
    if meta.get('sha256') != hashlib.sha256(audio).hexdigest(): raise ValueError('audio hash mismatch')
    with wave.open(io.BytesIO(audio), 'rb') as stream:
        if stream.getnchannels() != 1 or stream.getsampwidth() != 2 or stream.getframerate() != 16000 or not 0 < stream.getnframes() <= 16000 * 120:
            raise ValueError('expected up to 120 seconds of mono 16 kHz PCM')
        frames = stream.getnframes(); duration = frames / 16000
        if len(stream.readframes(frames)) != frames * 2: raise ValueError('truncated audio')
    exchange = MaterialExchange(root)
    result = exchange.import_mobile(meta, audio, start, revision, duration)
    try:
        from material_ingest import ingest_recordings_and_transcripts
        report = ingest_recordings_and_transcripts(root, exchange=exchange, only_mobile=(meta['deviceId'], meta['id']))
        result['indexPending'] = bool(report['errors']) or report['audio'] != 1 or report['transcript'] != 1
    except Exception:
        # The original phone audio is already saved; a retry must never discard it.
        result['indexPending'] = True
    return result



def refresh_gateway(root, port=8768):
    try:
        token = read_gateway_token(root)
        req = urllib.request.Request(f'http://127.0.0.1:{port}/v1/refresh', data=b'{}', headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as response: return response.status == 200
    except Exception: return False


def make_handler(root, token, gateway_port=8768, remote_manager=None, hosts=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def reply(self, status, body):
            data = json.dumps(body).encode(); self.send_response(status)
            self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(data)
        def authorized(self):
            return (hosts is None or self.headers.get('Host','').lower() in hosts) and self.headers.get('Origin') is None and hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token)
        def do_GET(self):
            if not self.authorized(): self.reply(401, {'error': 'unauthorized'}); return
            self.reply(200, {'status': 'ready', 'schema': 'audio-memory-sync/v1'}) if self.path == '/v1/sync/health' else self.reply(404, {'error': 'unknown endpoint'})
        def do_POST(self):
            if not self.authorized(): self.reply(401, {'error': 'unauthorized'}); return
            if self.path in ('/v1/sync/remote','/v1/sync/remote/stop') and remote_manager is not None:
                if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                    self.reply(403, {'error':'desktop-only control'}); return
                try:
                    value = remote_manager.start() if self.path.endswith('/remote') else remote_manager.stop()
                    if hasattr(remote_manager,'onchange'):remote_manager.onchange()
                    self.reply(200, value)
                except Exception:
                    self.reply(503, {'status':'error','message':'远程连接未能建立，请稍后重试并查看日志。'})
                return
            if self.path != '/v1/sync/recordings': self.reply(404, {'error': 'unknown endpoint'}); return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= MAX_PACKAGE or self.headers.get('Transfer-Encoding'): raise ValueError('invalid body size')
                self.connection.settimeout(30)
                body = self.rfile.read(size)
                if len(body) != size: raise ValueError('incomplete upload')
                result = import_package(root, body)
                result['gatewayRefreshed'] = refresh_gateway(root, gateway_port)
                self.reply(200, result)
            except FileExistsError: self.reply(409, {'error': 'record version conflicts; original retained'})
            except (ValueError, KeyError, TypeError, zipfile.BadZipFile, wave.Error, EOFError): self.reply(400, {'error': 'invalid recording package'})
            except Exception: self.reply(500, {'error': 'save failed; retry later'})
    return Handler


def certificate(root):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    folder = Path(root) / 'config/mobile-sync'; folder.mkdir(parents=True, exist_ok=True)
    certfile, keyfile = folder / 'server.pem', folder / 'server-key.pem'
    if not certfile.exists() or not keyfile.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Audio Memory Private Sync')])
        now = dt.datetime.now(dt.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now-dt.timedelta(minutes=5))
                .not_valid_after(now+dt.timedelta(days=3650)).sign(key, hashes.SHA256()))
        keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    cert = x509.load_pem_x509_certificate(certfile.read_bytes())
    return certfile, keyfile, cert.fingerprint(hashes.SHA256()).hex()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--root', type=Path, default=default_data_root())
    parser.add_argument('--host', default='0.0.0.0'); parser.add_argument('--port', type=int, default=int(os.environ.get('AUDIO_MEMORY_TEST_SYNC_PORT',8769)))
    parser.add_argument('--stop-file', type=Path); parser.add_argument('--ready-file', type=Path)
    args = parser.parse_args(); root = args.root.resolve()
    folder = root / 'config/mobile-sync'; folder.mkdir(parents=True, exist_ok=True)
    tokenfile = folder / 'access-token'
    try:
        with tokenfile.open('x', encoding='ascii') as stream: stream.write(secrets.token_urlsafe(32))
    except FileExistsError: pass
    token = tokenfile.read_text(encoding='ascii').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', token): raise ValueError('invalid sync token')
    cert, key, fingerprint = certificate(root)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert), str(key))
    from mobile_sync_remote import MobileRemote
    remote_manager = MobileRemote(root, int(os.environ.get('AUDIO_MEMORY_TEST_GATEWAY_PORT',8768)))
    server = ThreadingHTTPServer((args.host, args.port), make_handler(root, token, int(os.environ.get('AUDIO_MEMORY_TEST_GATEWAY_PORT',8768)), remote_manager)); server.daemon_threads = True
    server.socket = context.wrap_socket(server.socket, server_side=True)
    import psutil
    addresses = []
    stats = psutil.net_if_stats()
    private_ranges = [ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')]
    for name, entries in psutil.net_if_addrs().items():
        if name in stats and not stats[name].isup: continue
        for entry in entries:
            if entry.family != socket.AF_INET: continue
            value = entry.address; ip = ipaddress.ip_address(value)
            if any(ip in network for network in private_ranges): addresses.append((name,value))
    addresses.sort(key=lambda item: (not bool(re.search('wi.?fi|wlan|无线',item[0],re.I)),item[0]))
    pairings = []
    for name,address in addresses:
        value = {'url': f'https://{address}:{args.port}', 'token': token, 'fingerprint': fingerprint}
        code = 'am1.' + base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode().rstrip('=')
        pairings.append({'address': address, 'interface':name, 'code': code})
    status = root / 'out/mobile-sync-status.json'
    previous = None
    status_lock = threading.Lock()
    def publish():
        nonlocal previous
        with status_lock:
            value = {'status':'ready','pairings':pairings,'remote':remote_manager.status()}
            if value != previous: atomic(status,value); previous=value
    remote_manager.onchange=publish
    publish()
    if args.ready_file: args.ready_file.write_text('ready')
    server.timeout = .5
    try:
        while not args.stop_file or not args.stop_file.exists():
            server.handle_request(); publish()
    finally:
        remote_manager.shutdown(); server.server_close(); atomic(status, {'status': 'stopped', 'pairings': [], 'remote':{'status':'stopped'}})


if __name__ == '__main__': main()
