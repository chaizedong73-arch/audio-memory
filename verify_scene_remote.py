"""Explicit network integration check using isolated synthetic data; retains evidence."""
import io,json,os,sys,time,urllib.request,urllib.error
from pathlib import Path
from PIL import Image
import classroom_mode
from scene_capture import Capture
from scene_remote import RemoteTransport

def main():
 root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True);classroom_mode.set_enabled(root,True)
 capture=Capture(root);capture.region_mode='full';transport=RemoteTransport(capture);report={}
 try:
  started=time.monotonic();info=transport.start();report['startupSeconds']=round(time.monotonic()-started,2);report['origin']=info['origin']
  def request(path,body=None,authenticated=True):
   headers={'Authorization':'Bearer '+transport.token} if authenticated else {}
   req=urllib.request.Request(info['origin']+path,data=body,headers=headers)
   with urllib.request.urlopen(req,timeout=20) as response:return response.read()
  for attempt in range(5):
   try:
    assert b'getUserMedia' in request('/',authenticated=False);break
   except (OSError,AssertionError):
    if attempt==4:raise
    time.sleep(2)
  report['httpsPage']=True
  try:request('/phone',authenticated=False);raise AssertionError('Missing credential was accepted')
  except urllib.error.HTTPError as error:assert error.code==403
  report['unauthorizedRejected']=True
  request('/hello',b'{"device":"synthetic-integration-check"}')
  image=io.BytesIO();Image.new('RGB',(320,180),'#345678').save(image,'PNG');request('/frame',image.getvalue())
  assert (capture.folder/'preview.png').read_bytes()==image.getvalue();report['syntheticFrameSaved']=True
  phone=json.loads(request('/phone'));assert phone['connected'] and 'wifi' not in phone and 'frame' not in phone;report['minimalStatus']=True
  try:request('/wifi',b'{}');raise AssertionError('Desktop controls exposed')
  except urllib.error.HTTPError as error:assert error.code==404
  report['desktopControlBlocked']=True
  request('/command',b'{"name":"disconnect"}');assert capture.closing;report['disconnect']=True
  report['passed']=True
 except Exception as error:report.update(passed=False,error=str(error));raise
 finally:
  transport.close();capture.locator.close();capture.ocr_queue.put(None);report['stopped']=transport.closed
  (root/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
  print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
