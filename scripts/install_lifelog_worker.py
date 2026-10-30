"""Install the Mac lifelog worker as a restartable, hidden user service."""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

if __name__ == '__main__':
    if sys.platform != 'darwin':
        raise SystemExit('macOS only')
    root = Path(__file__).resolve().parents[1]
    state = Path.home() / '.dan' / 'lifelog'
    state.mkdir(parents=True, exist_ok=True)
    model = os.environ.get('DAN_LIFELOG_MODEL', 'mobiuslabsgmbh/faster-whisper-large-v3-turbo')
    name = 'com.dan.lifelog'
    plist = Path.home() / 'Library' / 'LaunchAgents' / (name + '.plist')
    if plist.exists():
        raise SystemExit('Service already installed; inspect before replacing')
    data = {'Label': name, 'ProgramArguments': [sys.executable, str(root / 'scripts/lifelog_worker.py')],
            'WorkingDirectory': str(root), 'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 30,
            'EnvironmentVariables': {'DAN_LIFELOG_MODEL': model, 'DAN_LIFELOG_DEVICE': 'cpu'},
            'StandardOutPath': str(state / 'service.log'), 'StandardErrorPath': str(state / 'service.log')}
    plist.write_bytes(plistlib.dumps(data))
    subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(plist)], check=True)
    print('installed', name)
