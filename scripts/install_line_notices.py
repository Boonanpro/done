"""Install the LINE notification recorder on the Mac (launchd com.dan.line-notices); does not restart Core or chat.

It runs `python -m app.services.line_notices` from the live tree: every 30 s it reads the Galaxy's notifications
(`adb shell dumpsys notification`, read only) and keeps each LINE message once in ~/.dan/line-notices/<YYYY-MM>.jsonl.
"""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.line_notices import ROOT as DATA

LABEL = 'com.dan.line-notices'


def install():
    if sys.platform != 'darwin': raise RuntimeError('Mac installer')
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = Path.home()/f'Library/LaunchAgents/{LABEL}.plist'
    if path.exists(): raise RuntimeError('Already installed; do not interrupt a running job')
    config = {'Label': LABEL, 'ProgramArguments': [sys.executable, '-m', 'app.services.line_notices'],
              'WorkingDirectory': str(ROOT), 'RunAtLoad': True, 'KeepAlive': True,
              'StandardOutPath': str(DATA/'recorder.log'), 'StandardErrorPath': str(DATA/'recorder.log'),
              'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:' + os.environ.get('PATH', ''), 'PYTHONUNBUFFERED': '1'}}
    path.write_bytes(plistlib.dumps(config))
    subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(path)], check=True)


if __name__ == '__main__': install()
