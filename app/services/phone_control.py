"""Phones and tablets connected to this PC (adb), operated the way Dan operates a browser (owner, 2026-10-03): the screen
is read as a list of its parts with refs, a part is pressed by its name or ref, text is typed, the screen scrolls. Before,
Dan built adb commands by hand each time and found where to tap from screenshots (slow, and taps landed by coordinates).

One call returns the screen after the action (no separate look). Reading a screen takes about 2 s (uiautomator's dump);
a screenshot (0.4 s) is only for what the parts list cannot show.

Irreversible presses (pay, order, send, delete, confirm…) need `confirmed: true`, given only after the owner approved
that exact action. Text other than ASCII cannot be typed through adb's input without an input app on the phone."""
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ADB = os.environ.get('DAN_ADB') or shutil.which('adb') or str(Path.home()/'AppData'/'Local'/'Android'/'Sdk'/'platform-tools'/'adb.exe')
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
_screens = {}   # serial -> {ref: item} of the last screen read
SENSITIVE = re.compile(r'購入|支払|決済|注文|送信|削除|確定|申し込|申込|契約|振込|送金|退会|解約|Pay|Buy|Order|Purchase|Send|Delete|Confirm|Subscribe', re.I)
KEYS = {'back': 'KEYCODE_BACK', 'home': 'KEYCODE_HOME', 'enter': 'KEYCODE_ENTER', 'recents': 'KEYCODE_APP_SWITCH',
        'delete': 'KEYCODE_DEL', 'tab': 'KEYCODE_TAB', 'search': 'KEYCODE_SEARCH'}

TOOL = {
    'name': 'phone',
    'description': ('PCにUSBやWi-Fiでつながったスマホ・タブレット（Android）を操作する。画面は部品の一覧（@p1 などの参照・種類・文字）で読み、'
                    '押す・入力・スクロールをした後の画面も同じ呼び出しで返す。座標やスクリーンショットから押す場所を割り出さない。'
                    'action: devices（つながっている機器）/ read（今の画面）/ tap（ref か label の文字で押す）/ type（文字を入れる。ref で欄を指定）/ '
                    'scroll（up/down/left/right）/ key（back/home/enter/recents/delete/tab/search）/ open（アプリを package 名で起動）/ '
                    'screenshot（部品の一覧で分からない見た目を確かめる時だけ）。購入・送信・削除・確定などの取り返しのつかない押下は、'
                    '本人がその操作を承認した時だけ confirmed=true で。'),
    'input_schema': {'type': 'object', 'properties': {
        'action': {'type': 'string', 'enum': ['devices', 'read', 'tap', 'type', 'scroll', 'key', 'open', 'screenshot']},
        'serial': {'type': 'string', 'description': '機器のシリアル（1台だけなら省略）'},
        'ref': {'type': 'string', 'description': 'tap/type: 画面の部品の参照（@p3）'},
        'label': {'type': 'string', 'description': 'tap: 押す部品の文字（ref の代わり。一つに決まる時だけ押す）'},
        'text': {'type': 'string', 'description': 'type: 入れる文字'},
        'direction': {'type': 'string', 'enum': ['up', 'down', 'left', 'right']},
        'key': {'type': 'string', 'enum': list(KEYS)},
        'package': {'type': 'string', 'description': 'open: アプリの package 名（例 com.twitter.android）'},
        'confirmed': {'type': 'boolean', 'description': '取り返しのつかない押下を本人が承認済み'},
    }, 'required': ['action'], 'additionalProperties': False},
}


def _adb(serial, *args, timeout=30, binary=False):
    cmd = [ADB] + (['-s', serial] if serial else []) + list(args)
    out = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
    return out.stdout if binary else out.stdout.decode('utf-8', 'replace') + out.stderr.decode('utf-8', 'replace')


def devices():
    rows = []
    for line in _adb('', 'devices', '-l').splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == 'device':
            model = next((p.split(':', 1)[1] for p in parts if p.startswith('model:')), '')
            rows.append({'serial': parts[0], 'model': model})
    return rows


def _serial(serial):
    if serial:
        return serial
    found = devices()
    if len(found) == 1:
        return found[0]['serial']
    raise ValueError('機器が見つからない' if not found else '複数の機器がつながっている。serial を指定する: ' + ', '.join(f"{d['serial']}({d['model']})" for d in found))


def _bounds(text):
    m = re.findall(r'\d+', text or '')
    return tuple(map(int, m[:4])) if len(m) >= 4 else (0, 0, 0, 0)


def read(serial):
    """The current screen as parts with refs; remembered for tap/type by ref."""
    raw = _adb(serial, 'exec-out', 'uiautomator', 'dump', '--compressed', '/dev/tty', timeout=30)
    xml = raw[raw.find('<?xml'):raw.rfind('</hierarchy>') + len('</hierarchy>')] if '<hierarchy' in raw else ''
    focus = re.search(r'mCurrentFocus=Window\{[^ ]+ [^ ]+ ([^}]+)\}', _adb(serial, 'shell', 'dumpsys', 'window', timeout=10))
    items, lines = {}, []
    if xml:
        root = ET.fromstring(xml)
        n = 0
        for node in root.iter('node'):
            a = node.attrib
            text, desc = (a.get('text') or '').strip(), (a.get('content-desc') or '').strip()
            cls = (a.get('class') or '').split('.')[-1]
            editable = cls in ('EditText', 'AutoCompleteTextView') or a.get('password') == 'true'
            clickable = a.get('clickable') == 'true' or a.get('long-clickable') == 'true'
            if not (text or desc or editable or (clickable and (a.get('resource-id') or ''))):
                continue
            x1, y1, x2, y2 = _bounds(a.get('bounds'))
            name = text or desc or (a.get('resource-id') or '').split('/')[-1]
            if all(0xE000 <= ord(c) <= 0xF8FF or 0xF0000 <= ord(c) or c.isspace() for c in name):
                name = '' if not clickable else (a.get('resource-id') or '').split('/')[-1] or 'アイコン'   # an icon-font glyph
            if x2 <= x1 or y2 <= y1 or not name:
                continue
            if lines and not (clickable or editable) and items[f'@p{n}']['name'] == name:
                continue   # the label inside the button just listed
            n += 1
            ref = f'@p{n}'
            kind = '入力欄' if editable else 'ボタン' if clickable else '文字'
            extra = ''.join([' [選択中]' if a.get('checked') == 'true' or a.get('selected') == 'true' else '',
                             ' [無効]' if a.get('enabled') == 'false' else '',
                             ' [スクロール可]' if a.get('scrollable') == 'true' else '',
                             f' 「{desc}」' if text and desc and desc != text else ''])
            items[ref] = {'name': name, 'kind': kind, 'center': ((x1 + x2) // 2, (y1 + y2) // 2), 'clickable': clickable or editable}
            lines.append(f'{ref} [{kind}] {name[:80]}{extra}')
    _screens[serial] = items
    head = f'画面: {focus.group(1) if focus else "?"}（部品{len(items)}個）'
    return head + '\n' + ('\n'.join(lines) if lines else '（部品を読めなかった。画面が切り替わり中か、読めない画面。少し待って read、または screenshot）')


def _target(serial, ref, label):
    items = _screens.get(serial) or {}
    if ref:
        item = items.get(ref if ref.startswith('@') else '@' + ref)
        if not item:
            raise ValueError(f'{ref} は今の画面の一覧にない（read し直す）')
        return item
    want = (label or '').strip().lower()
    exact = [i for i in items.values() if i['name'].strip().lower() == want]
    hits = exact or [i for i in items.values() if want and want in i['name'].lower()]
    clickable = [i for i in hits if i['clickable']]
    hits = clickable or hits
    if len(hits) != 1:
        raise ValueError(f'「{label}」に当たる部品が{len(hits)}個ある（ref で指定する）' if hits else f'「{label}」は今の画面に見当たらない')
    return hits[0]


def _after(serial, wait=.6):
    time.sleep(wait)   # the app redraws after the touch
    return read(serial)


def run(params):
    action = params.get('action')
    if action == 'devices':
        found = devices()
        return '\n'.join(f"{d['serial']} {d['model']}" for d in found) or 'つながっている機器はない（USB デバッグの許可とケーブルを確かめる）'
    serial = _serial(params.get('serial'))
    if action == 'read':
        return read(serial)
    if action == 'screenshot':
        path = Path('D:/done/uploads')/f'phone-{int(time.time())}.png'
        path.write_bytes(_adb(serial, 'exec-out', 'screencap', '-p', binary=True))
        return f'スクリーンショット: {path}（画像として読む）'
    if action == 'tap':
        if not _screens.get(serial):
            read(serial)
        item = _target(serial, params.get('ref'), params.get('label'))
        if SENSITIVE.search(item['name']) and not params.get('confirmed'):
            return f'押していない: 「{item["name"]}」は取り返しのつかない操作かもしれない。本人にこの操作を確かめ、承認されたら confirmed=true で押す。'
        _adb(serial, 'shell', 'input', 'tap', *map(str, item['center']))
        return f'押した: {item["name"]}\n' + _after(serial)
    if action == 'type':
        text = str(params.get('text') or '')
        if not text.isascii():
            return '入れていない: adb の文字入力は英数字だけ。日本語は、スマホに入力用のアプリ（ADBKeyboard など）を入れるか、本人に入れてもらう。'
        if params.get('ref') or params.get('label'):
            if not _screens.get(serial):
                read(serial)
            item = _target(serial, params.get('ref'), params.get('label'))
            _adb(serial, 'shell', 'input', 'tap', *map(str, item['center']))
            time.sleep(.3)
        _adb(serial, 'shell', 'input', 'text', text.replace(' ', '%s').replace("'", "\\'").replace('&', '\\&'))
        return '入れた\n' + _after(serial, .4)
    if action == 'scroll':
        size = re.search(r'(\d+)x(\d+)', _adb(serial, 'shell', 'wm', 'size', timeout=10))
        w, h = (int(size.group(1)), int(size.group(2))) if size else (1080, 2340)
        cx, cy = w // 2, h // 2
        dx, dy = {'up': (0, h // 3), 'down': (0, -h // 3), 'left': (w // 3, 0), 'right': (-w // 3, 0)}[params.get('direction') or 'down']
        _adb(serial, 'shell', 'input', 'swipe', str(cx - dx // 2), str(cy - dy // 2), str(cx + dx // 2), str(cy + dy // 2), '250')
        return 'スクロールした\n' + _after(serial, .5)
    if action == 'key':
        _adb(serial, 'shell', 'input', 'keyevent', KEYS[params.get('key') or 'back'])
        return f'{params.get("key")} を押した\n' + _after(serial)
    if action == 'open':
        package = str(params.get('package') or '')
        if not re.fullmatch(r'[A-Za-z0-9_.]+', package):
            return 'package 名が要る（例 com.twitter.android）'
        _adb(serial, 'shell', 'monkey', '-p', package, '-c', 'android.intent.category.LAUNCHER', '1')
        return f'{package} を開いた\n' + _after(serial, 1.5)
    return f'未知の action: {action}'


async def tool(params):
    import asyncio
    try:
        return {'success': True, 'output': await asyncio.to_thread(run, params)}
    except ValueError as exc:
        return {'success': False, 'error': str(exc)}
    except Exception as exc:
        return {'success': False, 'error': f'{type(exc).__name__}: {str(exc)[:300]}'}
