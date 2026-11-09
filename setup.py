"""Install and diagnose the portable local recording/transcription core."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT=Path(__file__).resolve().parent
ENV=ROOT/'.venv'
PYTHON=ENV/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
MODULES=('numpy','sounddevice','faster_whisper','opencc','soxr','psutil','av')
VISION_MODULES=('PIL','cv2','imageio_ffmpeg','cryptography','qrcode')

def doctor(vision=False):
    print('Python:',sys.version.split()[0], 'project:', ROOT)
    missing=[name for name in MODULES if importlib.util.find_spec(name) is None]
    print('Missing dependencies:', ', '.join(missing) if missing else 'none')
    if missing: return 1
    if vision:
        missing_vision=[name for name in VISION_MODULES if importlib.util.find_spec(name) is None]
        print('Missing vision dependencies:', ', '.join(missing_vision) if missing_vision else 'none')
        if missing_vision: return 1
    import sounddevice as sd
    try:
        devices=sd.query_devices()
        count=sum(1 for d in devices if d['max_input_channels']>0)
        print('Input devices:',count)
        if not count:
            print('No microphone found; connect one or allow microphone access. Existing audio can still be transcribed.')
            return 0
    except Exception as exc:
        print('Microphone detection failed; recording is unavailable until fixed:',exc); return 0
    print('Cloud AI and AI Workbench are optional and require separate setup.')
    return 0

def main():
    ap=argparse.ArgumentParser();ap.add_argument('command',choices=['install','doctor']);ap.add_argument('--vision',action='store_true',help='also install local camera/PPT dependencies');args=ap.parse_args()
    if sys.version_info[:2] != (3,13):raise SystemExit('This tested dependency set requires Python 3.13; other versions are not yet validated.')
    if args.command=='doctor':raise SystemExit(doctor(args.vision))
    if not PYTHON.exists():venv.EnvBuilder(with_pip=True).create(ENV)
    subprocess.run([str(PYTHON),'-m','pip','install','-r',str(ROOT/'requirements-core.txt')],check=True)
    if args.vision:subprocess.run([str(PYTHON),'-m','pip','install','-r',str(ROOT/'requirements-vision.txt')],check=True)
    from material_store import initialize
    from data_location import data_root as default_data_root
    print('Local materials database:', initialize(default_data_root()))
    raise SystemExit(subprocess.call([str(PYTHON),str(__file__),'doctor']+(['--vision'] if args.vision else [])))

if __name__=='__main__':main()
