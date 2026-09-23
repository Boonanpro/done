"""desktop: operate Windows apps the way the browser tool operates pages.

Dan could not touch desktop apps at all (LINE, Discord, installers, settings dialogs): there was no tool.
Same shape as the browser tool so both model backends and voice-delegated work use it the same way:
windows -> observe (elements with refs) -> find / click(ref|label) / type / read, plus a screenshot for
apps that expose nothing to UI Automation (then click by coordinates on that window).

Elements come from Windows UI Automation at call time; nothing is prepared per app. Actions use UIA
patterns (Invoke / Toggle / Select / SetValue) first, which do not move the owner's mouse or need focus;
the mouse is used only when asked for. Anything that sends, posts, pays or deletes needs confirmed=true:
the caller must already have the owner's approval (for messages: the compose_message card).
"""
import asyncio
import base64
import io
import re
import time

TOOL = {
    'name': 'desktop',
    'description': (
        'このPCのデスクトップアプリ（LINE、Discord、設定画面、インストーラなどブラウザ以外）を操作する。'
        'windows: 開いているウィンドウの一覧。observe(window): そのウィンドウの押せる物・入力欄の一覧(ref付き)と文字。'
        'find(window, query): 表示文字で探す。click(ref または window+label): 押す。type(ref, text): 入力欄に入れる（press_enter可）。'
        'read(window): 画面の文字を読む。screenshot(window): 画面を画像で見る（一覧に何も出ないアプリ用。その後 click(window,x,y) で座標を押せる）。'
        'launch(app): スタートメニューの名前でアプリを起動。focus(window): 前面に出す。'
        'keys(window, keys): そのウィンドウにキー操作を送る（pywinauto 表記: ^w=Ctrl+W, %{F4}=Alt+F4, ^l=Ctrl+L, {TAB}, {ESC}, ^s 等）。'
        'タブを閉じる・アプリの画面を切り替える・保存・戻るなど、部品の一覧に無い操作の大半はこれで足りる。'
        'window(window, op): ウィンドウそのものを close / minimize / maximize / restore。'
        'act(ref, op): 部品に expand / collapse / scroll_into_view / toggle / select / focus。'
        'script(code): 上で足りない時だけ、pywinauto を使う Python を1手で実行（Desktop, window(title) が使える。print した内容が返る）。'
        'ファイルを書いてシェルで動かすより速く、作業場所も汚さない。'
        '送信・投稿・支払い・削除にあたるボタンは confirmed=true が無いと押さない。'
        '外部の相手へのメッセージは、先に compose_message の送信案カードで本人の承認を得てから confirmed=true を付ける。'
    ),
    'input_schema': {'type': 'object', 'properties': {
        'action': {'type': 'string', 'enum': ['windows', 'observe', 'find', 'click', 'type', 'read', 'screenshot', 'launch', 'focus', 'keys', 'window', 'act', 'script']},
        'keys': {'type': 'string', 'maxLength': 200, 'description': 'keys: 送るキー（pywinauto 表記）'},
        'op': {'type': 'string', 'description': 'window: close/minimize/maximize/restore、act: expand/collapse/scroll_into_view/toggle/select/focus'},
        'code': {'type': 'string', 'maxLength': 8000, 'description': 'script: 実行する Python（pywinauto）'},
        'window': {'type': 'string', 'description': 'ウィンドウのタイトルの一部（windows の一覧にある文字）'},
        'ref': {'type': 'string'}, 'label': {'type': 'string', 'maxLength': 200}, 'query': {'type': 'string', 'maxLength': 200},
        'text': {'type': 'string', 'maxLength': 4000}, 'press_enter': {'type': 'boolean'},
        'replace': {'type': 'boolean', 'description': 'type: 既に文字が入っている欄を丸ごと置き換えてよい時だけ true'},
        'x': {'type': 'integer'}, 'y': {'type': 'integer'}, 'app': {'type': 'string', 'maxLength': 100},
        'confirmed': {'type': 'boolean', 'description': '送信・投稿・支払い・削除にあたる操作について、本人の承認を既に得ている時だけ true'},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 400},
    }, 'required': ['action'], 'additionalProperties': False},
}

SENSITIVE = re.compile(r'送信|投稿|公開|購入|注文|決済|支払|削除|退会|解約|ブロック|通報|\b(send|post|publish|pay|purchase|buy|delete|remove|block|report|unsubscribe)\b', re.I)
PRESSABLE = {'Button', 'Hyperlink', 'MenuItem', 'TabItem', 'ListItem', 'CheckBox', 'RadioButton', 'TreeItem', 'SplitButton', 'ComboBox'}
INPUTS = {'Edit', 'Document', 'ComboBox'}
_refs = {}          # ref -> element wrapper (valid while this MCP process lives and the element exists)
_counter = [0]


def _uia():
    from pywinauto import Desktop
    return Desktop(backend='uia')


def _text(result, **extra):
    return {'success': True, 'output': result, **extra}


def _fail(message):
    return {'success': False, 'error': message}


def _windows():
    out = []
    for w in _uia().windows():
        try:
            title = w.window_text().strip()
            if title and w.is_visible():
                out.append((title, w))
        except Exception:
            continue
    return out


def _window(title):
    if not title:
        raise ValueError('window（タイトルの一部）が必要です。windows で一覧を確認してください')
    hits = [(t, w) for t, w in _windows() if title.lower() in t.lower()]
    if not hits:
        raise ValueError(f'「{title}」を含むウィンドウが開いていません。windows で確認するか launch で起動してください')
    exact = [h for h in hits if h[0].lower() == title.lower()]
    return (exact or hits)[0]


def _describe(element):
    info = element.element_info
    name = (info.name or '').strip()
    return info.control_type or '', re.sub(r'\s+', ' ', name)[:120]


def _elements(window, limit):
    started = time.perf_counter()
    items = []
    for element in window.descendants():
        try:
            kind, name = _describe(element)
            if kind not in PRESSABLE and kind not in INPUTS:
                continue
            if not element.is_visible() or (not name and kind not in INPUTS):
                continue
            _counter[0] += 1
            ref = f'@d{_counter[0]}'
            _refs[ref] = element
            items.append({'ref': ref, 'kind': kind, 'name': name, 'enabled': bool(element.is_enabled())})
            if len(items) >= limit:
                break
        except Exception:
            continue
    if len(_refs) > 5000:
        for key in list(_refs)[:2500]:
            _refs.pop(key, None)
    return items, round((time.perf_counter()-started)*1000)


def _window_text(window, limit=6000):
    seen, out = set(), []
    for element in window.descendants():
        try:
            kind, name = _describe(element)
            if name and kind in ('Text', 'Edit', 'Document', 'ListItem', 'Hyperlink', 'Button') and name not in seen:
                seen.add(name); out.append(name)
                if sum(len(x) for x in out) > limit:
                    break
        except Exception:
            continue
    return '\n'.join(out)


def _press(element, use_mouse=False):
    """UIA patterns first: they act without moving the owner's pointer or taking the keyboard."""
    if not use_mouse:
        for pattern, call in (('invoke', 'invoke'), ('toggle', 'toggle'), ('select', 'select'), ('expand', 'expand')):
            try:
                getattr(element, call)()
                return pattern
            except Exception:
                continue
    element.click_input()
    return 'mouse'


def _resolve(params):
    if params.get('ref'):
        element = _refs.get(params['ref'])
        if element is None:
            raise ValueError('その ref はもう使えません。observe か find をやり直してください')
        return element
    title, window = _window(params.get('window'))
    want = re.sub(r'\s+', ' ', params.get('label') or '').strip()
    if not want:
        raise ValueError('ref か、window と label が必要です')
    items, _ = _elements(window, 400)
    hits = [i for i in items if i['name'] == want] or [i for i in items if want.lower() in i['name'].lower()]
    if len(hits) != 1:
        listing = '\n'.join(f"  {i['ref']}: [{i['kind']}] {i['name']}" for i in hits[:12])
        raise ValueError((f'「{want}」に当たる物が {len(hits)} 個あります。何も押していません。ref で指定してください:\n{listing}') if hits
                         else f'「{want}」に当たる物が見つかりません。observe か find で確認してください。何も押していません。')
    return _refs[hits[0]['ref']]


def _run(params):
    action = params.get('action')
    if action == 'windows':
        rows = [t for t, _ in _windows()]
        return _text('開いているウィンドウ:\n' + '\n'.join('  '+t for t in rows) if rows else '見えているウィンドウがありません')
    if action == 'launch':
        import subprocess
        app = (params.get('app') or '').strip()
        if not app or not re.fullmatch(r'[\w .+\-ぁ-んァ-ヶ一-龠ー]{1,100}', app):
            return _fail('app にスタートメニューに出るアプリ名を指定してください')
        found = subprocess.run(['powershell', '-NoProfile', '-Command',
            f"(Get-StartApps | Where-Object {{ $_.Name -eq '{app}' }} | Select-Object -First 1).AppID"], capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout.strip()
        if not found:
            return _fail(f'スタートメニューに「{app}」という名前のアプリがありません')
        subprocess.Popen(['explorer.exe', 'shell:AppsFolder\\'+found], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return _text(f'{app} を起動しました。数秒後に windows で確認してください。')
    if action in ('observe', 'find', 'read', 'screenshot', 'focus') or (action == 'click' and params.get('x') is not None):
        title, window = _window(params.get('window'))
        if action == 'focus':
            window.set_focus(); return _text(f'「{title}」を前面に出しました')
        if action == 'read':
            return _text(f'ウィンドウ「{title}」の文字:\n'+_window_text(window))
        if action == 'screenshot':
            image = window.capture_as_image()
            if image.width > 1400:
                image = image.resize((1400, int(image.height*1400/image.width)))
            buffer = io.BytesIO(); image.convert('RGB').save(buffer, format='JPEG', quality=70)
            rect = window.rectangle()
            return {'success': True, 'content': [
                {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': base64.b64encode(buffer.getvalue()).decode()}},
                {'type': 'text', 'text': f'ウィンドウ「{title}」の画像（実寸 {rect.width()}x{rect.height()}、画像は幅{image.width}に縮小）。'
                                          f'click(window, x, y) の座標はウィンドウ左上からの実寸で渡す（画像上の座標 × {rect.width()/image.width:.3f}）。'}]}
        if action == 'click':
            if not params.get('confirmed'):
                return _fail('座標クリックは何を押すか確認できないため confirmed=true が必要です（本人の承認済みの操作だけ）')
            window.click_input(coords=(int(params['x']), int(params['y'])))
            return _text(f'「{title}」の ({params["x"]},{params["y"]}) を押しました。observe か screenshot で結果を確認してください')
        items, ms = _elements(window, params.get('limit', 150))
        if action == 'find':
            query = (params.get('query') or '').lower()
            if not query:
                return _fail('query が必要です')
            items = [i for i in items if query in i['name'].lower()]
        lines = [f'ウィンドウ「{title}」: {len(items)} 個（取得 {ms}ms）'] + [
            f"  {i['ref']}: [{i['kind']}]{'' if i['enabled'] else ' (無効)'} {i['name']}" for i in items]
        if not items and action == 'observe':
            lines.append('このアプリは部品の一覧を公開していません。screenshot で画面を見て、click(window, x, y) を使ってください。')
        return _text('\n'.join(lines), count=len(items))
    if action in ('click', 'type'):
        element = _resolve(params)
        kind, name = _describe(element)
        if not element.is_enabled():
            return _fail(f'[{kind}] {name} は無効になっていて操作できません')
        if action == 'click':
            if SENSITIVE.search(name) and not params.get('confirmed'):
                return _fail(f'「{name}」は送信・投稿・支払い・削除にあたる操作です。本人の承認を得てから confirmed=true を付けてください。何も押していません。')
            how = _press(element)
            return _text(f'[{kind}] {name} を押しました（{how}）。observe で結果を確認してください')
        text = params.get('text')
        if not isinstance(text, str):
            return _fail('text が必要です')
        # Setting a value replaces everything in the control. In an editor that is the owner's document
        # (found the hard way: a test overwrote the unsaved buffer of an open Notepad tab). Never do that silently.
        try:
            existing = element.iface_value.CurrentValue or ''
        except Exception:
            try: existing = element.window_text() or ''
            except Exception: existing = ''
        if existing.strip() and not params.get('replace'):
            return _fail(f'この欄には既に {len(existing)} 文字入っています（先頭: {existing[:40]!r}）。入力すると全部置き換わります。'
                         '置き換えてよい時だけ replace=true を付けてください。何も入力していません。')
        if params.get('press_enter') and not params.get('confirmed'):
            return _fail('入力後のEnterはメッセージの送信になりうるため confirmed=true が必要です。Enterなしで入力だけ行うか、承認を得てください。')
        try:
            element.iface_value.SetValue(text); how = 'value'
        except Exception:
            element.set_focus(); element.type_keys(text, with_spaces=True, with_newlines=False, pause=0.01); how = 'keys'
        if params.get('press_enter'):
            element.type_keys('{ENTER}')
        return _text(f'[{kind}] {name or "入力欄"} に入力しました（{how}{"・Enter" if params.get("press_enter") else ""}）。値は observe / read で確認できます')
    if action == 'keys':
        title, window = _window(params.get('window'))
        keys = params.get('keys') or ''
        if not keys:
            return _fail('keys が必要です')
        if '{ENTER}' in keys.upper() and not params.get('confirmed'):
            return _fail('Enter はメッセージの送信になりうるため confirmed=true が必要です。何も送っていません。')
        try:
            window.set_focus()
        except Exception:
            pass
        window.type_keys(keys, with_spaces=True, pause=0.02, set_foreground=True)
        return _text(f'「{title}」に {keys} を送りました。windows / observe で結果を確認してください')
    if action == 'window':
        title, window = _window(params.get('window'))
        op = params.get('op')
        calls = {'close': 'close', 'minimize': 'minimize', 'maximize': 'maximize', 'restore': 'restore'}
        if op not in calls:
            return _fail('op は close / minimize / maximize / restore')
        getattr(window, calls[op])()
        return _text(f'「{title}」を {op} しました')
    if action == 'act':
        element = _resolve(params)
        kind, name = _describe(element)
        op = params.get('op')
        if op not in ('expand', 'collapse', 'scroll_into_view', 'toggle', 'select', 'focus'):
            return _fail('op は expand / collapse / scroll_into_view / toggle / select / focus')
        if op in ('toggle', 'select') and SENSITIVE.search(name) and not params.get('confirmed'):
            return _fail(f'「{name}」は送信・支払い・削除にあたる操作です。本人の承認を得てから confirmed=true を付けてください。')
        {'focus': element.set_focus}.get(op, lambda: getattr(element, op)())()
        return _text(f'[{kind}] {name} を {op} しました')
    if action == 'script':
        return _script(params.get('code') or '')
    return _fail('action は windows / observe / find / click / type / read / screenshot / launch / focus / keys / window / act / script のいずれか')


def _script(code):
    """pywinauto code in this process, one step: what a job would otherwise write to a file and run through the shell
    (two steps, a Python start each time, and files left behind). print() output is returned."""
    import contextlib, io as _io
    if not code.strip():
        return _fail('code が必要です')
    try:
        from app.agent.v2.tools import _note_fallback
        _note_fallback('desktop_script', code[:300])
    except Exception:
        pass
    out = _io.StringIO()
    scope = {'Desktop': lambda: _uia(), 'window': lambda title: _window(title)[1], 'time': time, 're': re}
    try:
        with contextlib.redirect_stdout(out):
            exec(compile(code, '<desktop script>', 'exec'), scope)
    except Exception as exc:
        return _fail(f'{type(exc).__name__}: {str(exc)[:400]}' + (chr(10) + '出力: ' + out.getvalue()[:2000] if out.getvalue() else ''))
    return _text(out.getvalue()[:6000] or '（出力なし）')


async def run(params):
    try:
        return await asyncio.to_thread(_run, params)
    except ValueError as exc:
        return _fail(str(exc))
    except Exception as exc:
        return _fail(f'デスクトップ操作に失敗しました: {type(exc).__name__}: {str(exc)[:200]}')
