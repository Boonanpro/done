"""手元カメラの在席の時間を残す処理（scripts/desk_presence_keep.py）を launchd com.dan.desk-presence-keep に入れる。

1時間ごとに `desk_presence_keep.py --manage-retention` を動いているダン（~/done）から起こす。
1回の実行は最長50分。launchd は前の実行が終わるまで次を起こさない。入れ直しは --reinstall。
"""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = 'com.dan.desk-presence-keep'
LIVE = Path.home() / 'done'
DATA = Path.home() / '.dan/workspace/data/desk-presence-keep'
PYTHON = Path.home() / 'dan-venv/bin/python'


def install(reinstall=False):
    if sys.platform != 'darwin':
        raise RuntimeError('Mac installer')
    DATA.mkdir(parents=True, exist_ok=True)
    path = Path.home() / f'Library/LaunchAgents/{LABEL}.plist'
    domain = f'gui/{os.getuid()}'
    if path.exists():
        if not reinstall:
            raise RuntimeError('Already installed; use --reinstall')
        subprocess.run(['launchctl', 'bootout', f'{domain}/{LABEL}'], check=False)
    config = {'Label': LABEL,
              'ProgramArguments': [str(PYTHON), '-u', str(LIVE / 'scripts/desk_presence_keep.py'),
                                   '--manage-retention'],
              'WorkingDirectory': str(LIVE), 'StartInterval': 3600, 'RunAtLoad': True,
              'LowPriorityIO': True, 'Nice': 10,
              'StandardOutPath': str(DATA / 'launchd.log'), 'StandardErrorPath': str(DATA / 'launchd.log'),
              'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
                                       'PYTHONUNBUFFERED': '1'}}
    path.write_bytes(plistlib.dumps(config))
    subprocess.run(['launchctl', 'bootstrap', domain, str(path)], check=True)
    print(f'{LABEL} を入れました（1時間ごと）')


if __name__ == '__main__':
    install('--reinstall' in sys.argv)
