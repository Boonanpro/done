"""家の中の直通（scripts/lan_media_server.py）を launchd に登録して起こす。何度走らせてもよい。

  python scripts/install_lan_media.py           # 登録（あれば起こし直す）して、応答を確かめる
  python scripts/install_lan_media.py --remove  # 止めて登録を外す（エディターは今までの道だけで読む）
"""
import json
import os
import plistlib
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = Path.home() / 'done'          # 動いているダン（.env と同じ場所で起こす）
LABEL = 'com.dan.lan-media'
PLIST = Path.home() / 'Library/LaunchAgents' / f'{LABEL}.plist'
LOG = Path.home() / '.dan/lan-media/server.log'


def main():
    if sys.platform != 'darwin':
        raise SystemExit('Mac mini でだけ動かす')
    domain = f'gui/{os.getuid()}'
    subprocess.run(['launchctl', 'bootout', f'{domain}/{LABEL}'], capture_output=True)
    if '--remove' in sys.argv:
        PLIST.unlink(missing_ok=True)
        route = Path.home() / '.dan/lan-media/route.json'
        if route.exists():
            d = json.loads(route.read_text()); d['alive'] = False; route.write_text(json.dumps(d))
        print('止めました'); return
    LOG.parent.mkdir(parents=True, exist_ok=True)
    value = {'Label': LABEL,
             'ProgramArguments': [sys.executable, str(LIVE / 'scripts/lan_media_server.py')],
             'WorkingDirectory': str(LIVE), 'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 10,
             'StandardOutPath': str(LOG), 'StandardErrorPath': str(LOG),
             'EnvironmentVariables': {'PATH': os.environ.get('PATH', '/opt/homebrew/bin:/usr/bin:/bin'),
                                      'PYTHONUNBUFFERED': '1'}}
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    with PLIST.open('wb') as f:
        plistlib.dump(value, f)
    subprocess.run(['launchctl', 'bootstrap', domain, str(PLIST)], check=True)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen('https://dan-home.paina.info/lan/ping', timeout=3) as r:
                if json.load(r).get('ok'):
                    print('家の中の直通が動いています: https://dan-home.paina.info'); return
        except Exception:
            time.sleep(1)
    raise SystemExit(f'起きませんでした。記録: {LOG}')


if __name__ == '__main__':
    main()
