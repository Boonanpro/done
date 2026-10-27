"""Install the local gateway only after a release is verified. No Core is stopped."""
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core import generations as G


def install():
    if sys.platform != 'darwin': raise RuntimeError('This installer is for the active Mac')
    active = G.read('active')
    if not active or not G.living(active.get('owner')): raise RuntimeError('Prepare and activate a healthy release first')
    directory = Path.home() / 'Library/LaunchAgents'
    path = directory / 'com.dan.gateway.plist'
    log = G.ROOT / 'gateway.log'
    value = {'Label': 'com.dan.gateway', 'ProgramArguments': [sys.executable, str(ROOT / 'scripts/run_gateway.py')],
             'WorkingDirectory': str(ROOT), 'RunAtLoad': True, 'KeepAlive': True,
             'StandardOutPath': str(log), 'StandardErrorPath': str(log),
             'EnvironmentVariables': {'PATH': os.environ.get('PATH', ''), 'PYTHONUNBUFFERED': '1'}}
    directory.mkdir(parents=True, exist_ok=True)
    # Installing twice never bootouts a gateway that has active streams.
    if not path.exists():
        with path.open('wb') as stream: plistlib.dump(value, stream)
        subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(path)], check=True)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            for port in (9100, 8100):
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/_gateway/health', timeout=2) as response:
                    if not json.load(response).get('ready'): raise RuntimeError('Gateway not ready')
            (G.ROOT / 'enabled').touch()
            print('Gateway ready; rebuild frontend to use it.'); return
        except Exception: time.sleep(.5)
    raise RuntimeError('Gateway did not start; frontend routing was not changed')


if __name__ == '__main__': install()
