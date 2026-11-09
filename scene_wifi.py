"""Opt-in private-LAN HTTPS transport. Project-local CA; no system trust changes."""
import datetime,hashlib,ipaddress,json,os,socket,ssl,subprocess,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from cryptography import x509
from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from classroom_mode import save

TLS_PORT=19644
CERT_PORT=19645

def local_ip():
 if os.name=='nt':
  # A VPN's default route can report its private TUN address, unreachable by phones.
  command="Get-NetIPConfiguration -Detailed | Where-Object { $_.NetAdapter.HardwareInterface -and $_.NetAdapter.Status -eq 'Up' -and $_.IPv4DefaultGateway } | ForEach-Object { $_.IPv4Address.IPAddress }"
  result=subprocess.run(['powershell.exe','-NoProfile','-Command',command],capture_output=True,text=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  if result.returncode:raise ValueError('无法读取物理网卡地址，请检查 Wi-Fi 连接')
  for value in result.stdout.splitlines():
   value=value.strip()
   try:ip=ipaddress.ip_address(value)
   except ValueError:continue
   if ip.version==4 and ip.is_private and not ip.is_loopback and not ip.is_link_local and ip not in ipaddress.ip_network('198.18.0.0/15'):return value
  raise ValueError('未找到可用的物理局域网IPv4地址，请连接 Wi-Fi 或网线')
 with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
  sock.connect(('192.0.2.1',9));value=sock.getsockname()[0]
 ip=ipaddress.ip_address(value)
 if not ip.is_private or ip.is_loopback or ip.is_link_local:raise ValueError('未找到可用的局域网IPv4地址')
 return value

def certificates(root,ip):
 folder=Path(root)/'config/scene-tls';folder.mkdir(parents=True,exist_ok=True)
 if os.name=='nt':
  user=os.environ.get('USERDOMAIN','')+'\\'+os.environ.get('USERNAME','')
  result=subprocess.run(['icacls',str(folder),'/inheritance:r','/grant:r',user+':(OI)(CI)F','SYSTEM:(OI)(CI)F'],capture_output=True,timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  if result.returncode:raise ValueError('无法保护局域网证书私钥，未开启无线接入')
 now=datetime.datetime.now(datetime.timezone.utc)
 key_file=folder/'ca-key.pem';ca_file=folder/'ca.pem'
 if key_file.exists() and ca_file.exists():
  ca=x509.load_pem_x509_certificate(ca_file.read_bytes());key=serialization.load_pem_private_key(key_file.read_bytes(),None)
  if ca.not_valid_after_utc<=now:raise ValueError('项目无线证书已过期，需要更新并重新安装手机证书')
 else:
  key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
  name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'AI Recording Camera Local CA')])
  ca=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
      .not_valid_before(now-datetime.timedelta(minutes=5)).not_valid_after(now+datetime.timedelta(days=365))
      .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
      .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),critical=False)
      .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),critical=False)
      .add_extension(x509.KeyUsage(digital_signature=True,key_encipherment=False,key_cert_sign=True,crl_sign=True,content_commitment=False,data_encipherment=False,key_agreement=False,encipher_only=False,decipher_only=False),critical=True)
      .sign(key,hashes.SHA256()))
  key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));ca_file.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
 (folder/'camera-ca.cer').write_bytes(ca.public_bytes(serialization.Encoding.DER))
 server_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
 cert=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'AI Recording Camera LAN')]))
       .issuer_name(ca.subject).public_key(server_key.public_key()).serial_number(x509.random_serial_number())
       .not_valid_before(now-datetime.timedelta(minutes=5)).not_valid_after(min(now+datetime.timedelta(days=7),ca.not_valid_after_utc))
       .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
       .add_extension(x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()),critical=False)
       .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),critical=False)
       .add_extension(x509.KeyUsage(digital_signature=True,key_encipherment=True,key_cert_sign=False,crl_sign=False,content_commitment=False,data_encipherment=False,key_agreement=False,encipher_only=False,decipher_only=False),critical=True)
       .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip))]),critical=False)
       .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False).sign(key,hashes.SHA256()))
 (folder/'server-key.pem').write_bytes(server_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
 (folder/'server.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM)+ca.public_bytes(serialization.Encoding.PEM))
 return folder,ca.fingerprint(hashes.SHA256()).hex().upper()

class TLSHTTPServer(ThreadingHTTPServer):
 def __init__(self,address,handler,context):self.context=context;super().__init__(address,handler)
 def get_request(self):
  sock,addr=super().get_request();sock.settimeout(8)
  try:return self.context.wrap_socket(sock,server_side=True),addr
  except Exception:sock.close();raise

class WifiTransport:
 def __init__(self,capture,ip=None):
  from scene_capture import handler
  self.capture=capture;self.ip=ip or local_ip();self.servers=[];self.threads=[]
  address=ipaddress.ip_address(self.ip)
  if not address.is_private or address.is_loopback:raise ValueError('无线接入仅允许局域网IPv4')
  folder,fingerprint=certificates(capture.root,self.ip)
  context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
  context.load_cert_chain(str(folder/'server.pem'),str(folder/'server-key.pem'))
  host=f'{self.ip}:{TLS_PORT}';origin=f'https://{host}'
  cert_host=f'{self.ip}:{CERT_PORT}'
  ca_bytes=(folder/'camera-ca.cer').read_bytes()
  class Download(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    if self.path!='/camera-ca.cer' or self.headers.get('Host')!=cert_host:
     self.send_error(404);return
    self.send_response(200);self.send_header('Content-Type','application/x-x509-ca-cert');self.send_header('Content-Disposition','attachment; filename="camera-ca.cer"')
    self.send_header('Content-Length',str(len(ca_bytes)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(ca_bytes)
  try:
   self.servers.append(TLSHTTPServer((self.ip,TLS_PORT),handler(capture,hosts={host},origins={origin},remote=True),context))
   self.servers.append(ThreadingHTTPServer((self.ip,CERT_PORT),Download))
  except Exception:
   for server in self.servers:server.server_close()
   raise
  url=origin+'/#'+capture.token;certificate_url=f'http://{self.ip}:{CERT_PORT}/camera-ca.cer'
  import qrcode
  pairing=capture.folder/'wifi';pairing.mkdir(exist_ok=True)
  qrcode.make(certificate_url).save(pairing/'certificate-qr.png');qrcode.make(url).save(pairing/'capture-qr.png')
  self.info={'enabled':True,'ip':self.ip,'url':url,'certificateUrl':certificate_url,'fingerprint':fingerprint,
             'certificateQr':str(pairing/'certificate-qr.png'),'captureQr':str(pairing/'capture-qr.png'),
             'caName':'AI Recording Camera Local CA','certificatePath':str(folder/'camera-ca.cer')}
  save(pairing/'pairing.json',self.info)
 def start(self):
  for server in self.servers:
   server.daemon_threads=True;thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.2},daemon=True);thread.start();self.threads.append(thread)
 def close(self):
  for server in self.servers:server.shutdown();server.server_close()
  for thread in self.threads:thread.join(timeout=2)
  for name in ('capture-qr.png','pairing.json'):
   try:(self.capture.folder/'wifi'/name).unlink()
   except FileNotFoundError:pass
