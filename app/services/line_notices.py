"""The owner's personal LINE, read from the notifications on the Galaxy that is cabled to this Mac (read only, 2026-11-13).

Why: the owner said 「APIで早く正確になるものは積極的に取り入れて良い」「正確なまま早くする」. A personal LINE account has no
API to read it, and opening LINE on the phone with taps takes half a minute and more. The Galaxy S24 (LINE as a sub device
of the owner's own account) receives every message as a notification, and Android hands the notification's content to
`adb shell dumpsys notification --noredact` in about 0.3 s: the talk's name, the sender, each message's text and time.

What a notification cannot give: messages already read (LINE takes the notification away), photos and stickers (only
「写真を送信しました」 and the like), and the owner's own replies. So a small recorder (`python -m app.services.line_notices`,
launchd com.dan.line-notices) reads the notifications every 30 s and keeps each message once in
~/.dan/line-notices/<YYYY-MM>.jsonl; what came in while the recorder ran stays answerable after it was read.

Nothing here taps the phone or changes its screen; `dumpsys` only reads. Sending stays with the outbound card.
"""
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PACKAGE = 'jp.naver.line.android'
SERIAL = os.environ.get('DAN_LINE_PHONE_SERIAL', 'RFCXB0MSSTD')   # the development Galaxy S24 (phone-operation skill)
ROOT = Path.home()/'.dan'/'line-notices'
INTERVAL_S = 30
JST = ZoneInfo('Asia/Tokyo')
ADB = os.environ.get('DAN_ADB') or shutil.which('adb') or '/opt/homebrew/bin/adb'
_RECORD = re.compile(r'^\s{4}NotificationRecord\(', re.M)
_MESSAGE = re.compile(r'\[\d+\] Bundle\[\{extras=Bundle\[\{MESSAGE_ID=(\d+)\}\], sender_person=\S+, sender=(.*?), text=(.*?), time=(\d{12,14})\}\]', re.S)


class Unavailable(Exception):
    """The phone is not connected or did not answer."""


def _dump(serial=SERIAL, timeout=10):
    try:
        out = subprocess.run([ADB, '-s', serial, 'shell', 'dumpsys', 'notification', '--noredact'],
                             capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Unavailable(f'Galaxy に届かなかった（{type(exc).__name__}）')
    text = out.stdout.decode('utf-8', 'replace')
    if out.returncode != 0 or 'NotificationRecord' not in text:
        raise Unavailable('Galaxy がつながっていない（' + (out.stderr.decode('utf-8', 'replace').strip()[:120] or '応答なし') + '）')
    return text


def _extras(block):
    """The plain extras of one notification (title, text, conversationTitle...). A value may run over several lines."""
    start = block.find('extras={')
    if start < 0:
        return {}
    body = block[start:block.find('\n      stats=', start) if '\n      stats=' in block[start:] else len(block)]
    found = {}
    lines = body.split('\n')
    key, value = None, []
    for line in lines[1:]:
        m = re.match(r'^\s{16}([A-Za-z0-9_.]+)=(\w+(?:\[\])?) ?(.*)$', line)
        if m:
            if key: found[key] = '\n'.join(value)
            key, kind, rest = m.group(1), m.group(2), m.group(3)
            if kind in ('String', 'Boolean', 'Integer') and rest.startswith('('):
                value = [rest[1:]]
            else:
                key, value = None, []
        elif key:
            value.append(line)
    if key: found[key] = '\n'.join(value)
    return {k: v[:-1] if v.endswith(')') else v for k, v in found.items()}


def parse(dump):
    """Every LINE message the notifications hold now: [{id, talk, sender, text, at (epoch s), group}]."""
    out = {}
    starts = [m.start() for m in _RECORD.finditer(dump)] + [len(dump)]
    for a, b in zip(starts, starts[1:]):
        block = dump[a:b]
        if f'pkg={PACKAGE} ' not in block[:300]:
            continue
        extras = _extras(block)
        talk = extras.get('android.conversationTitle') or extras.get('android.subText') or ''
        group = extras.get('android.isGroupConversation') == 'true' or bool(talk)
        messages = list(_MESSAGE.finditer(block))
        for m in messages:
            mid, sender, text, stamp = m.group(1), m.group(2).strip(), m.group(3).strip(), int(m.group(4))
            out[mid] = {'id': mid, 'talk': talk or sender, 'sender': sender, 'text': text, 'at': stamp / 1000, 'group': group}
        if not messages and extras.get('android.text') and 'GROUP_SUMMARY' not in block[:600]:
            title = extras.get('android.title') or ''
            if title == 'LINE':   # 「〇〇が友だちになりました」 and LINE's own notices
                continue
            stamp = re.search(r'when=(\d{12,14})', block)
            mid = extras.get('line.message.id') or f"n{stamp.group(1) if stamp else ''}{abs(hash(title)) % 10**6}"
            out[mid] = {'id': mid, 'talk': talk or title, 'sender': title.split(': ')[-1], 'text': extras.get('android.text', ''),
                        'at': int(stamp.group(1)) / 1000 if stamp else time.time(), 'group': group}
    return sorted(out.values(), key=lambda r: r['at'])


def now(serial=SERIAL):
    return parse(_dump(serial))


# ---- the recorder ------------------------------------------------------------------------------------------------------

def _file(moment):
    return ROOT/f"{datetime.fromtimestamp(moment, JST):%Y-%m}.jsonl"


def recorded(days=7):
    since = time.time() - days * 86400
    rows = []
    months = sorted({_file(since), _file(time.time())})
    for path in months:
        if not path.exists():
            continue
        for line in path.read_text(encoding='utf-8').splitlines():
            try: row = json.loads(line)
            except ValueError: continue
            if row.get('at', 0) >= since:
                rows.append(row)
    return rows


def record_once(known):
    """Adds the messages not kept yet; returns how many."""
    added = 0
    for row in now():
        if row['id'] in known:
            continue
        known.add(row['id'])
        path = _file(row['at'])
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open('a', encoding='utf-8') as f:
            f.write(json.dumps({**row, 'seen_at': time.time()}, ensure_ascii=False) + '\n')
        added += 1
    return added


def main():
    known = {r['id'] for r in recorded(days=40)}
    failing = 0
    while True:
        try:
            added = record_once(known)
            if added: print(f'{datetime.now(JST):%m-%d %H:%M:%S} +{added}', flush=True)
            failing = 0
        except Unavailable as exc:
            failing += 1
            if failing in (1, 20) or failing % 120 == 0:
                print(f'{datetime.now(JST):%m-%d %H:%M:%S} {exc}', flush=True)
        except Exception as exc:   # one bad dump must not stop the recorder
            print(f'{datetime.now(JST):%m-%d %H:%M:%S} {type(exc).__name__}: {exc}', flush=True)
        time.sleep(INTERVAL_S)


if __name__ == '__main__':
    main()
