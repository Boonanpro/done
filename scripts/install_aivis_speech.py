"""台本を聞く画面（/script-listen）の声を作る AivisSpeech Engine を Mac mini に入れて、launchd で常駐させる。
何度走らせてもよい（入っていれば起こし直して、声を確かめるだけ）。無料・手元で動く。

  python scripts/install_aivis_speech.py           # 入れる・起こす・声のモデルを入れる
  python scripts/install_aivis_speech.py --remove  # 止めて登録を外す（ファイルは残す）

声は app/services/script_listen.py の VOICES。モデルは AivisHub から入れる（MODELS）。
"""
import os
import plistlib
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

VERSION = '1.2.0'
HOME = Path.home() / '.dan' / 'aivis-speech'
ENGINE = HOME / 'macOS-arm64'
LABEL = 'com.dan.aivis-speech'
PLIST = Path.home() / 'Library/LaunchAgents' / f'{LABEL}.plist'
LOG = HOME / 'engine.log'
PORT = 10101
URL = (f'https://github.com/Aivis-Project/AivisSpeech-Engine/releases/download/{VERSION}/'
       f'AivisSpeech-Engine-macOS-arm64-{VERSION}.7z.001')
MODELS = {  # AivisHub の uuid（11/18 の聞き比べで選んだ男性の声）
    '阿井田 茂': '47e53151-a378-46f3-abee-ce13aa07feb1',
    'Shinjou Tomoharu': '098d4e66-2faf-4a00-889c-a1d2f05bde78',
    'M1': 'd7255c2c-ddd0-425a-808c-662cd94c7f41',
}


def _alive():
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/version', timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _speakers():
    import json
    with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/speakers', timeout=10) as r:
        return {s['name'] for s in json.load(r)}


def _download():
    if (ENGINE / 'run').exists(): return
    seven = shutil.which('7zz') or shutil.which('7z')
    if not seven:
        subprocess.run(['brew', 'install', 'sevenzip'], check=True)
        seven = shutil.which('7zz')
    HOME.mkdir(parents=True, exist_ok=True)
    archive = HOME / 'engine.7z.001'
    print('AivisSpeech Engine を落としています（約200MB）…')
    subprocess.run(['curl', '-sL', '-o', str(archive), URL], check=True)
    subprocess.run([seven, 'x', '-y', str(archive), f'-o{HOME}'], check=True, capture_output=True)
    subprocess.run(['xattr', '-dr', 'com.apple.quarantine', str(ENGINE)], capture_output=True)
    archive.unlink(missing_ok=True)


def main():
    if sys.platform != 'darwin':
        raise SystemExit('Mac mini でだけ動かす')
    domain = f'gui/{os.getuid()}'
    subprocess.run(['launchctl', 'bootout', f'{domain}/{LABEL}'], capture_output=True)
    for _ in range(30):   # bootout returns before the old job is gone; bootstrap fails (error 5) until it is
        if subprocess.run(['launchctl', 'print', f'{domain}/{LABEL}'], capture_output=True).returncode != 0: break
        time.sleep(0.5)
    if '--remove' in sys.argv:
        PLIST.unlink(missing_ok=True); print('止めました'); return
    _download()
    value = {'Label': LABEL,
             'ProgramArguments': [str(ENGINE / 'run'), '--host', '127.0.0.1', '--port', str(PORT), '--disable_sentry'],
             'WorkingDirectory': str(ENGINE), 'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 10,
             'ProcessType': 'Interactive', 'StandardOutPath': str(LOG), 'StandardErrorPath': str(LOG)}
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    with PLIST.open('wb') as f:
        plistlib.dump(value, f)
    subprocess.run(['launchctl', 'bootstrap', domain, str(PLIST)], check=True)
    deadline = time.monotonic() + 120
    while not _alive():
        if time.monotonic() > deadline: raise SystemExit(f'起きませんでした。記録: {LOG}')
        time.sleep(1)
    have = _speakers()
    for name, uuid in MODELS.items():
        if name in have: continue
        print(f'声「{name}」を入れています…')
        body = f'url=https://api.aivis-project.com/v1/aivm-models/{uuid}/download?model_type=AIVMX'
        subprocess.run(['curl', '-s', '-X', 'POST', f'http://127.0.0.1:{PORT}/aivm_models/install',
                        '-F', body], check=True)
    missing = [n for n in MODELS if n not in _speakers()]
    if missing: raise SystemExit(f'入らなかった声: {missing}')
    print(f'読み上げの道具が動いています: http://127.0.0.1:{PORT}（声 {len(MODELS)} 人）')


if __name__ == '__main__':
    main()
