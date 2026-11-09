"""USB transport setup only; device permission always remains on the phone."""
from data_location import data_root as default_data_root
import argparse,json,os,subprocess,sys,time,socket,uuid
from pathlib import Path
from scene_capture import ROOT,PORT

def connect(root=ROOT,probe=False,tools_root=ROOT):
 root=Path(root);adb=Path(tools_root)/'tools/android/platform-tools/adb.exe'
 if not adb.exists():raise ValueError('项目内缺少安卓USB工具')
 runtime=root/'out/scene/runtime.json'
 if not runtime.exists():raise ValueError('请先启动手机接收')
 state=json.loads(runtime.read_text(encoding='utf-8-sig'))
 def listening(port):
  try:
   with socket.create_connection(('127.0.0.1',port),timeout=.3):return True
  except OSError:return False
 port=state.get('adbPort')
 if not port:
  if listening(5037):port=5037;owned=False
  else:
   port=5039;owned=True
   if listening(port):raise ValueError('项目USB端口5039已占用，不接管其他进程')
   registry=os.environ.get('AUDIO_MEMORY_REGISTRY_PATH')
   executable=os.environ.get('AUDIO_MEMORY_REGISTRY_EXECUTABLE')
   if not registry or not executable:raise ValueError('缺少进程管理配置，无法启动USB服务')
   log=(root/'logs/scene-usb.log');log.parent.mkdir(exist_ok=True)
   with log.open('ab') as output:
    subprocess.Popen([executable,str(registry),'run','--owner','GPT','--name','Scene-USB-'+uuid.uuid4().hex,'--desc','手机采集专用USB通道，结束采集时退出','--',str(adb),'-L','tcp:localhost:5039','server','nodaemon'],stdout=output,stderr=output,env={**os.environ,'ELECTRON_RUN_AS_NODE':'1'},creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   for _ in range(30):
    if listening(port):break
    time.sleep(.1)
   if not listening(port):raise ValueError('项目USB服务未能启动，请查看logs/scene-usb.log')
  state.update(adbPort=port,adbOwned=owned)
  from classroom_mode import save
  save(runtime,state)
 def run(args):
  result=subprocess.run([str(adb),'-P',str(port),*args],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=12,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  if result.returncode:raise ValueError('USB接入失败：'+result.stderr[-500:])
  return result.stdout
 # Reuse an existing shared server without stopping it; otherwise own a registered private server.
 rows=[line.split() for line in run(['devices']).splitlines()[1:] if line.strip()]
 devices=[row[0] for row in rows if len(row)>1 and row[1]=='device']
 if len(devices)>1:raise ValueError('检测到多台手机，请只保留本次测试的一台USB连接')
 if not devices:
  if any(len(row)>1 and row[1]=='unauthorized' for row in rows):raise ValueError('请解锁手机，在USB调试提示中点允许，然后重试')
  raise ValueError('尚未检测到可用手机：请在安卓开发者选项开启USB调试，保持数据线连接后重试；部分手机还需要厂商USB驱动')
 serial=devices[0]
 if probe:return '已检测到已授权的安卓USB设备，可通过工具箱打开采集页面'
 if state.get('usbSerial')!=serial:
  run(['-s',serial,'reverse','--no-rebind',f'tcp:{PORT}',f'tcp:{PORT}'])
  state['usbSerial']=serial
  from classroom_mode import save
  save(runtime,state)
 url=f'http://localhost:{PORT}/#'+state['token']
 run(['-s',serial,'shell','am','start','-a','android.intent.action.VIEW','-d',url])
 return '已打开手机采集页，请在手机点击开启后置摄像头并授权'

def cleanup(root=ROOT,tools_root=ROOT):
 root=Path(root);file=root/'out/scene/runtime.json'
 if not file.exists():return
 state=json.loads(file.read_text(encoding='utf-8-sig'));port=state.get('adbPort');adb=Path(tools_root)/'tools/android/platform-tools/adb.exe'
 if not port or not adb.exists():return
 try:
  with socket.create_connection(('127.0.0.1',int(port)),timeout=.3):pass
 except OSError:return # never let cleanup implicitly start a replacement ADB server
 def call(args):
  try:subprocess.run([str(adb),'-P',str(port),*args],capture_output=True,timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  except (OSError,subprocess.TimeoutExpired):pass
 if state.get('usbSerial'):call(['-s',state['usbSerial'],'reverse','--remove',f'tcp:{PORT}'])
 if state.get('adbOwned'):call(['kill-server'])

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=default_data_root());parser.add_argument('--disconnect',action='store_true');parser.add_argument('--probe',action='store_true');args=parser.parse_args()
 try:
  if args.disconnect:cleanup(args.root)
  else:print(connect(args.root,probe=args.probe))
 except Exception as error:print(str(error));sys.exit(1)
 finally:
  if args.probe:cleanup(args.root)
