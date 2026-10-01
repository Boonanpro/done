"""desktop: operate Windows apps the way the browser tool operates pages.

Dan could not touch desktop apps at all (LINE, Discord, installers, settings dialogs): there was no tool.
Same shape as the browser tool so both model backends and voice-delegated work use it the same way:
windows -> observe (elements with refs) -> find / click(ref|label) / type / read, plus a screenshot for
apps that expose nothing to UI Automation (then click by coordinates on that window).

Elements come from Windows UI Automation at call time; nothing is prepared per app. Actions use UIA
patterns (Invoke / Toggle / Select / SetValue) first, which do not move the owner's mouse or need focus;
the mouse is used only when asked for. Anything that sends, posts, pays or deletes needs confirmed=true:
the caller must already have the owner's approval (for messages: the compose_message card).

Operation memory, as for the browser (browser_flows): the steps a job takes in an app (launch, focus, click, type, keys)
are recorded with each element's kind and name, and kept as a flow when the work reaches a look at the result (read,
observe, find) or the job ends. The next time, `flow replay` runs them by code: each element is found again by kind and
name (an item the request named, by the new name), through the same _run as a model's call, so every confirmation gate
holds. A step that cannot be found stops the replay; the model carries on from there, and its fresh recording replaces
the flow. A script, or a click by coordinates on no readable text, is not a step code can repeat: such a run is not kept.

Apps that expose nothing to UI Automation (games, canvas-drawn apps) are read with Windows' own OCR: observe/find list the
window's text lines as refs (@t…), click(ref | window+label) presses the text's centre, and a click by coordinates on a
text is recorded as that text. A replay finds the text again by reading the window.
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
RECORD_IDLE_SECONDS = 900
STEP_WAIT_SECONDS = 8
_record = {'steps': [], 'updated': 0.0}   # this process's recording (a job runs in its own process)
_pending = []       # the step _run is taking; kept only when the call succeeds
_replaying = [False]


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


class TextTarget:
    """A line of text read off a window (OCR): what a click on an app with no UI Automation parts presses."""
    def __init__(self, window, text, box):
        self.window, self.text, self.box = window, text, box
        self.center = (int((box[0]+box[2])/2), int((box[1]+box[3])/2))


def _ocr(window):
    """The window's text lines with their boxes (window coordinates, real pixels), read by Windows' OCR."""
    import asyncio as _asyncio
    image = window.capture_as_image()

    async def read():
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.storage.streams import InMemoryRandomAccessStream, DataWriter
        buf = io.BytesIO(); image.save(buf, format='PNG')
        stream = InMemoryRandomAccessStream(); writer = DataWriter(stream)
        writer.write_bytes(buf.getvalue()); await writer.store_async(); writer.detach_stream(); stream.seek(0)
        bitmap = await (await BitmapDecoder.create_async(stream)).get_software_bitmap_async()
        engine = OcrEngine.try_create_from_language(Language('ja')) or OcrEngine.try_create_from_user_profile_languages()
        return await engine.recognize_async(bitmap)

    result = _asyncio.run(read())
    lines = []
    for line in result.lines:
        rects = [w.bounding_rect for w in line.words]
        if not rects:
            continue
        text = re.sub(r'(?<=[^\x00-\x7f]) | (?=[^\x00-\x7f])', '', line.text).strip()   # the OCR spaces Japanese characters apart
        box = (min(r.x for r in rects), min(r.y for r in rects), max(r.x+r.width for r in rects), max(r.y+r.height for r in rects))
        if text:
            lines.append(TextTarget(window, text, box))
    return lines


def _text_refs(targets):
    rows = []
    for target in targets:
        _counter[0] += 1
        ref = f'@t{_counter[0]}'
        _refs[ref] = target
        rows.append(f'  {ref}: [文字] {target.text}')
    return rows


def _text_named(window, want, names=None):
    from app.services.browser_flows import matches
    lines = _ocr(window)
    index = matches([t.text for t in lines], want)
    return None if index is None else lines[index]


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
    if not hits:
        target = _text_named(window, want)   # no part of that name: the text on the screen
        if target is not None:
            return target
    if len(hits) != 1:
        listing = '\n'.join(f"  {i['ref']}: [{i['kind']}] {i['name']}" for i in hits[:12])
        raise ValueError((f'「{want}」に当たる物が {len(hits)} 個あります。何も押していません。ref で指定してください:\n{listing}') if hits
                         else f'「{want}」に当たる物が見つかりません。observe か find で確認してください。何も押していません。')
    return _refs[hits[0]['ref']]


def _exe(element):
    try:
        import psutil
        return psutil.Process(element.element_info.process_id).name()
    except Exception:
        return ''


def _window_of(element):
    try:
        top = element.top_level_parent()
        return {'title': (top.window_text() or '').strip(), 'exe': _exe(top)}
    except Exception:
        return {'title': '', 'exe': ''}


def _identity(element):
    kind, name = _describe(element)
    try: auto_id = element.element_info.automation_id or ''
    except Exception: auto_id = ''
    try: siblings = sum(1 for e in element.parent().children() if e.element_info.control_type == kind)
    except Exception: siblings = 0
    return {'ref': {'role': kind, 'name': name, 'auto_id': auto_id}}, siblings


def _note(action, element=None, window=None, **extra):
    """The step this call is taking, for the recording (kept only if the call succeeds)."""
    if _replaying[0]:
        return
    step = {'action': action, **extra}
    if isinstance(element, TextTarget):
        step['targets'], step['siblings'] = {'ref': {'role': 'Text', 'name': element.text, 'auto_id': ''}}, 0
        step['window'] = {'title': (element.window.window_text() or '').strip(), 'exe': _exe(element.window)}
    elif element is not None:
        step['targets'], step['siblings'] = _identity(element)
        step['window'] = _window_of(element)
    elif window is not None:
        step['window'] = {'title': (window.window_text() or '').strip(), 'exe': _exe(window)}
    _pending.append(step)


FIXED_KEYS = re.compile(r'(?:[\^%+]+(?:\{[A-Za-z0-9_ ]+\}|.)|\{[A-Za-z0-9_ ]+\})+')


def _commit(params, result):
    """After a call: keep its step, mark the recording as not repeatable, or save it at a look at the result."""
    if _replaying[0]:
        return
    steps = list(_pending); _pending.clear()
    now = time.time()
    if now-_record['updated'] > RECORD_IDLE_SECONDS:
        _record.clear(); _record.update(steps=[], updated=now)
    action = params.get('action')
    if not result.get('success'):
        return
    if action == 'script' or (action == 'click' and params.get('x') is not None and not steps):
        _record['unrecordable'] = True   # what code cannot repeat by itself: this run teaches nothing
    elif steps:
        _record['steps'].extend(steps); _record['updated'] = now
    elif action in ('read', 'observe', 'find'):
        save()


def save(task=None):
    """The recording as a flow (browser_flows' store), when it has steps code can repeat."""
    steps = [dict(s) for s in _record.get('steps') or []]
    if len(steps) < 2 or _record.get('unrecordable'):
        return None
    try:
        from app.services import browser_flows, browser_recipes
        task = browser_recipes._task_words() if task is None else task
        exe = next((s['window']['exe'] for s in steps if (s.get('window') or {}).get('exe')), '') or 'app'
        host = 'desktop:' + exe
        for step in steps:
            step['pre'] = host
            window = step.get('window')
            if window and browser_flows.asked(window.get('title'), task):
                step['window'] = {**window, 'title': ''}   # a window named for what the request opened: found by the new name
        run = {'flow_steps': steps, 'flow_end': {'key': host, 'landmarks': []}, 'landing': host, 'kind': 'desktop',
               'saved': None, 'flow_saved': _record.get('flow_saved')}
        flow = browser_flows.save_flow(run, task)
        _record['flow_saved'] = run.get('flow_saved')
        return flow
    except Exception:
        return None


def finish():
    """The job is done: keep what it did in apps."""
    return save()


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
        _note('launch', app=app)
        return _text(f'{app} を起動しました。数秒後に windows で確認してください。')
    if action in ('observe', 'find', 'read', 'screenshot', 'focus') or (action == 'click' and params.get('x') is not None):
        title, window = _window(params.get('window'))
        if action == 'focus':
            window.set_focus(); _note('focus', window=window); return _text(f'「{title}」を前面に出しました')
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
            x, y = int(params['x']), int(params['y'])
            try:   # the text under the point, so the step can be found again by reading the screen
                hit = next((t for t in _ocr(window) if t.box[0] <= x <= t.box[2] and t.box[1] <= y <= t.box[3]), None)
            except Exception:
                hit = None
            if hit is not None:
                _note('click', hit)
            window.click_input(coords=(x, y))
            return _text(f'「{title}」の ({params["x"]},{params["y"]}) を押しました。observe か screenshot で結果を確認してください')
        items, ms = _elements(window, params.get('limit', 150))
        if action == 'find':
            query = (params.get('query') or '').lower()
            if not query:
                return _fail('query が必要です')
            items = [i for i in items if query in i['name'].lower()]
        lines = [f'ウィンドウ「{title}」: {len(items)} 個（取得 {ms}ms）'] + [
            f"  {i['ref']}: [{i['kind']}]{'' if i['enabled'] else ' (無効)'} {i['name']}" for i in items]
        if len(items) <= 4:
            # Only the title bar's buttons, or nothing: the app draws its own screen. Its text, read off the screen, is pressable.
            try:
                texts = _ocr(window)
            except Exception:
                texts = []
            if action == 'find':
                from app.services.browser_flows import _norm
                texts = [t for t in texts if _norm(params.get('query')) in _norm(t.text)]
            if texts:
                lines.append('画面の文字（このアプリは部品を公開していないので画面から読んだ。click(ref) でその文字を押せる）:')
                lines.extend(_text_refs(texts[:150]))
            elif action == 'observe' and not items:
                lines.append('このアプリは部品の一覧を公開していません。screenshot で画面を見て、click(window, x, y) を使ってください。')
        return _text('\n'.join(lines), count=len(items))
    if action in ('click', 'type'):
        element = _resolve(params)
        if isinstance(element, TextTarget):
            if action == 'type':
                return _fail('画面の文字は入力欄ではありません。入力欄を click してから keys で文字を送ってください。')
            if SENSITIVE.search(element.text) and not params.get('confirmed'):
                return _fail(f'「{element.text}」は送信・投稿・支払い・削除にあたる操作です。本人の承認を得てから confirmed=true を付けてください。何も押していません。')
            _note('click', element)
            element.window.click_input(coords=element.center)
            return _text(f'画面の文字「{element.text}」を押しました。observe で結果を確認してください')
        kind, name = _describe(element)
        if not element.is_enabled():
            return _fail(f'[{kind}] {name} は無効になっていて操作できません')
        if action == 'click':
            if SENSITIVE.search(name) and not params.get('confirmed'):
                return _fail(f'「{name}」は送信・投稿・支払い・削除にあたる操作です。本人の承認を得てから confirmed=true を付けてください。何も押していません。')
            _note('click', element)
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
        _note('type', element, slot=(name or kind or '入力')[:40], example=text,
              **({'replace': True} if params.get('replace') else {}), **({'press_enter': True} if params.get('press_enter') else {}))
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
        _note('keys', window=window, **({'keys': keys} if FIXED_KEYS.fullmatch(keys) else {'slot': 'キー入力', 'example': keys}))
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
        _note('window', window=window, op=op)
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
        _note('act', element, op=op)
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


def _call(params):
    _pending.clear()
    try:
        result = _run(params)
    except ValueError as exc:
        result = _fail(str(exc))
    except Exception as exc:
        result = _fail(f'デスクトップ操作に失敗しました: {type(exc).__name__}: {str(exc)[:200]}')
    try:
        _commit(params, result)
    except Exception:
        pass
    return result


async def run(params):
    return await asyncio.to_thread(_call, params)


# ---- replay -------------------------------------------------------------------

def _find_window(spec, values):
    """The step's window: the same title, else the app's window named by a value of this request, else the app's only window."""
    from app.services.browser_flows import matches
    windows = _windows()
    if spec.get('title'):
        same = [w for t, w in windows if t == spec['title']]
        if same:
            return same[0]
    mine = [(t, w) for t, w in windows if spec.get('exe') and _exe(w) == spec['exe']]
    for value in values.values():
        index = matches([t for t, _ in mine], str(value))
        if index is not None:
            return mine[index][1]
    return mine[0][1] if len(mine) == 1 else None


def _find_element(window, step, values):
    from app.services.browser_flows import matches
    want = step['targets']['ref']
    if want.get('role') == 'Text':   # recorded off the screen: read it again
        name = str(values.get(step['slot']) or step.get('example') or '') if step.get('pick') else want['name']
        return _text_named(window, name)
    items = []
    for element in window.descendants(control_type=want['role']) if want.get('role') else []:
        try:
            if element.is_visible() and element.is_enabled():
                items.append((_describe(element)[1], element))
        except Exception:
            continue
    if step.get('pick'):
        index = matches([n for n, _ in items], str(values.get(step['slot']) or step.get('example') or ''))
        return None if index is None else items[index][1]
    found = [e for n, e in items if n == want['name']]
    if len(found) > 1 and want.get('auto_id'):
        found = [e for e in found if (e.element_info.automation_id or '') == want['auto_id']] or found
    return found[0] if len(found) == 1 else None


def _wait(find, seconds=STEP_WAIT_SECONDS):
    deadline = time.perf_counter()+seconds
    while True:
        try:
            found = find()
        except Exception:
            found = None
        if found is not None or time.perf_counter() >= deadline:
            return found
        time.sleep(.3)


def _replay(flow, values):
    started, done, reason, title = time.perf_counter(), [], None, ''
    _replaying[0] = True
    try:
        for step in flow['steps']:
            action = step['action']
            if action == 'launch':
                result = _run({'action': 'launch', 'app': step['app']})
            else:
                window = _wait(lambda: _find_window(step.get('window') or {}, values), 15 if done and done[-1] == 'launch' else STEP_WAIT_SECONDS)
                if window is None:
                    raise RuntimeError('window_not_found: ' + ((step.get('window') or {}).get('exe') or ''))
                title = (window.window_text() or '').strip()
                if action in ('click', 'type', 'act'):
                    element = _wait(lambda: _find_element(window, step, values))
                    if element is None:
                        raise RuntimeError('element_not_found: ' + (step['targets']['ref'].get('role') or ''))
                    _counter[0] += 1
                    ref = f'@d{_counter[0]}'
                    _refs[ref] = element
                    params = {'action': action, 'ref': ref}
                    if action == 'type':
                        try: existing = element.iface_value.CurrentValue or ''
                        except Exception: existing = ''
                        # a search box still holding the last search is the procedure's own field; a document never is
                        short = step['targets']['ref'].get('role') == 'Edit' and chr(10) not in existing and len(existing) <= 200
                        params.update(text=str(values.get(step['slot']) or step.get('example') or ''),
                                      replace=bool(step.get('replace')) or short, press_enter=bool(step.get('press_enter')))
                    if action == 'act':
                        params['op'] = step['op']
                    result = _run(params)   # the same gates as a model's call: nothing is sent, paid or deleted unconfirmed
                elif action == 'keys':
                    result = _run({'action': 'keys', 'window': title, 'keys': step.get('keys') or str(values.get(step.get('slot')) or step.get('example') or '')})
                elif action in ('focus', 'window'):
                    result = _run({'action': action, 'window': title, **({'op': step['op']} if action == 'window' else {})})
                else:
                    raise RuntimeError('unknown_step: ' + action)
            if not result.get('success'):
                raise RuntimeError('step_failed: ' + str(result.get('error') or '')[:120])
            done.append(action)
    except Exception as exc:
        reason = str(exc)[:160]
    finally:
        _replaying[0] = False
    return {'replayed': reason is None, 'reason': reason, 'completed_steps': done, 'window': title,
            'elapsed_ms': round((time.perf_counter()-started)*1000)}


async def replay(flow, values):
    """Run a desktop flow by code; the caller reads the window it ends on (result['window'])."""
    return await asyncio.to_thread(_replay, flow, values)
