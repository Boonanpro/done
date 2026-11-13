"""Macの空きを保つ片付け（scripts/disk_tidy.py）を launchd com.dan.disk-tidy に入れる。Core やチャットは止めない。

1時間ごとに `disk_tidy.py --scheduled` を動いているダン（~/done）から起こす。片付けそのものは前の実行から20時間たった時か、
空きが100GBを切った時だけ動く。入れ直しは --reinstall（前の登録を外してから入れる）。
"""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = 'com.dan.disk-tidy'
LIVE = Path.home() / 'done'
DATA = Path.home() / '.dan/workspace/data/disk-tidy'
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
              'ProgramArguments': [str(PYTHON), '-u', str(LIVE / 'scripts/disk_tidy.py'), '--scheduled'],
              'WorkingDirectory': str(LIVE), 'StartInterval': 3600, 'RunAtLoad': False,
              'LowPriorityIO': True, 'Nice': 10,
              'StandardOutPath': str(DATA / 'launchd.log'), 'StandardErrorPath': str(DATA / 'launchd.log'),
              'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
                                       'PYTHONUNBUFFERED': '1'}}
    path.write_bytes(plistlib.dumps(config))
    subprocess.run(['launchctl', 'bootstrap', domain, str(path)], check=True)
    print(f'{LABEL} を入れました（1時間ごと）')


if __name__ == '__main__':
    install('--reinstall' in sys.argv)
