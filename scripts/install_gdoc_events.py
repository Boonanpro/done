"""Install the single event worker on the Mac; does not restart Core or chat."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.gdoc_events import ROOT as DATA

def install():
    if sys.platform != 'darwin': raise RuntimeError('Mac installer')
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = Path.home()/'Library/LaunchAgents/com.dan.gdoc-events.plist'
    if path.exists(): raise RuntimeError('Already installed; do not interrupt a running job')
    config = {'Label':'com.dan.gdoc-events', 'ProgramArguments':[sys.executable, '-m', 'app.services.gdoc_events'],
              'WorkingDirectory':str(ROOT), 'RunAtLoad':True, 'KeepAlive':True,
              'StandardOutPath':str(DATA/'worker.log'), 'StandardErrorPath':str(DATA/'worker.log'),
              'EnvironmentVariables':{'PATH':os.environ.get('PATH',''), 'PYTHONUNBUFFERED':'1'}}
    path.write_bytes(plistlib.dumps(config))
    subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(path)], check=True)

if __name__=='__main__': install()
