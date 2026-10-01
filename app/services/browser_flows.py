"""Operation memory beyond login: any sequence of browser steps the large model did once (open a site, fill a search
form, pick options, submit, read the result) is remembered as a FLOW with its typed values as slots, and replayed by
code next time with new values. First principles: never compute twice what does not change; the second time costs no
model call at all (a Jev choice at most, when an element moved).

Recording piggybacks on browser_recipes (every tool call already passes through it): here the run's non-login steps are
kept with their values, and a run that ended in reading a page (read/find/content/read_url) is saved as a flow.

    flow = {'id', 'host', 'start': url_key, 'name': task words, 'steps': [...], 'slots': {slot: shape},
            'end': {'key', 'landmarks'}, 'successes', 'failures', 'created', 'used'}
    step = {'action': 'click'|'type'|'select'|'keyboard_press'|'fill_credential'..., 'params': {...}, 'targets': {...},
            'slot': 'label of the field' (type/select/pick), 'shape': the value's form, 'pre': url_key, 'post': {...}}

A flow is the procedure only, never the values that went through it (2026-10-01): a slot keeps its form (「0000/00/00」,
「あああ」), not what was typed, and an item picked from a list because the request named it (a LINE group, an invoice)
is a slot too, not a fixed click. So a flow holds nothing of the person who recorded it and can serve anyone; the replay
gets every value from the request. Flows recorded before then still carry their example values and replay with them.
Values of password fields, credential steps and one-time codes are never stored (the login machinery handles those).
The same store and the same `flow` tool hold desktop apps' flows (host 'desktop:<exe>', see desktop_control).
Kill switch: DAN_BROWSER_FLOWS=0.
"""
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path

from app.services import browser_recipes as recipes

logger = logging.getLogger(__name__)
MAX_STEPS = 40
MIN_STEPS = 2
SECRET_LABEL = re.compile(r'パスワード|password|暗証|pin|セキュリティコード|cvv|認証コード|otp|token', re.I)


def enabled():
    return os.environ.get('DAN_BROWSER_FLOWS', '1') != '0' and recipes.enabled()


def root():
    path = Path(os.environ.get('DAN_BROWSER_FLOWS_DIR') or Path.home()/'.dan'/'browser-flows')
    path.mkdir(parents=True, exist_ok=True)
    return path


def _host_file(host):
    return root()/(re.sub(r'[^A-Za-z0-9.-]', '_', host or 'unknown')+'.json')


def _read_flows(path):
    """A host's flows. The file is encrypted at rest with the credentials' key: a recorded step can carry an identifier
    typed into the site (a registered IC card, a member number) as its example value, and that must not sit in plain
    JSON. A plain file from before 2026-09-22 is still read."""
    try: text = path.read_text(encoding='utf-8')
    except OSError: return []
    if not text.strip(): return []
    if text.lstrip().startswith('['):
        try: return json.loads(text)
        except ValueError: return []
    from app.services.encryption import decrypt_data
    try: return json.loads(decrypt_data(text.strip()))
    except Exception:
        logger.warning('flow file could not be decrypted: %s', path.name)
        return []


def _write_flows(path, flows):
    from app.services.encryption import encrypt_data
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(encrypt_data(json.dumps(flows, ensure_ascii=False)), encoding='utf-8')
    os.replace(temp, path)


def flows_for(host):
    return _read_flows(_host_file(host))


def all_flows():
    out = []
    for path in root().glob('*.json'):
        out.extend(_read_flows(path))
    return [f for f in out if not f.get('disabled')]


PICK_NAME_MAX = 4     # a calendar day, a seat row, a list number: the clicked name IS the value
PICK_GROUP_MIN = 5    # ...when it sits among a set of such siblings (a calendar has 28-31, a list a handful)


def pick_group(element, elements):
    """The set of short-named siblings this element was picked from (a calendar's days, a list's items); [] when it is not a pick."""
    name = element.get('name') or ''
    if not name or len(name) > PICK_NAME_MAX:
        return []
    shape = lambda n: 'number' if n.isdigit() else f'text{len(n)}'   # the set is homogeneous: days are all numbers, a lone 検索 button is not one of them
    group = sorted({e['name'] for e in elements if e.get('role') == element.get('role') and e.get('tag') == element.get('tag')
                    and e.get('name') and len(e['name']) <= PICK_NAME_MAX and shape(e['name']) == shape(name)},
                   key=lambda n: (int(n) if n.isdigit() else 0, n))
    return group if len(group) >= PICK_GROUP_MIN else []


ITEM_ROLES = {'link', 'listitem', 'option', 'row', 'gridcell', 'treeitem', 'menuitem', 'tab', 'radio',
              'Hyperlink', 'ListItem', 'TreeItem', 'DataItem', 'MenuItem', 'TabItem', 'RadioButton',   # page roles, then UIA kinds
              'Text'}   # a line read off an app's screen (OCR): its role is unknown, so only a long name counts (see generalize)
CHOICE_MIN_SIBLINGS = 3   # one item out of a list: a lone button the request happens to mention (「検索」) is not a choice


def _norm(text):
    import unicodedata
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text or '')).casefold()


def shape(value):
    """The form of a value without the value: digits become 0, Latin letters a, anything else あ."""
    value = re.sub(r'[a-zA-Z]', 'a', re.sub(r'[0-9]', '0', str(value)))
    return re.sub(r'[^0a\s\-/:.,@()]', 'あ', value)[:40]


def asked(name, task):
    """The part of a clicked item's name that the request itself said ('' when the request did not name it).
    「【X顧問】株式会社パイナ本田様（4人）」 clicked for 「【X顧問】株式会社パイナ本田様を開いて」 gives the group's name."""
    n, t = _norm(name), _norm(task)
    if len(n) < 2 or not t:
        return ''
    if n in t:
        return n
    best = ''
    for i in range(len(n)):   # the longest stretch of the name found in the request
        for j in range(len(n), i+len(best), -1):
            if n[i:j] in t:
                best = n[i:j]
                break
    return best if len(best) >= 4 and len(best)*2 >= len(n) else ''


def generalize(steps, task):
    """The recorded steps as a procedure: values become their shapes, and a click on a list item the request named becomes
    a pick slot (replayed by the name the next request gives)."""
    out, picks, typed = [], sum(1 for s in steps if s.get('pick')), []
    for step in steps:
        step = dict(step)
        if step['action'] in ('type', 'keys') and step.get('example'):
            typed.append(str(step['example']))
        target = (step.get('targets') or {}).get('ref') or {}
        part = asked(target.get('name'), task) if step['action'] == 'click' and not step.get('pick') else ''
        # one item out of a list, or the item a search just narrowed the list to (typed 「X顧問」, clicked 「【X顧問】…」)
        searched = any(len(_norm(t)) >= 2 and _norm(t) in _norm(target.get('name')) for t in typed)
        if target.get('role') == 'Text' and len(part) < 4:
            part = ''   # 「検索」 read off the screen may be a button: too short to tell an item from a control
        if part and target.get('role') in ITEM_ROLES and (step.get('siblings', 0) >= CHOICE_MIN_SIBLINGS or searched or target.get('role') == 'Text'):
            picks += 1
            step.update(slot=f'選ぶ項目{picks}', pick=True, named=True, example=part, said=part)
            step['targets'] = {'ref': {**target, 'name': ''}}   # found by the name the next request gives
        if step.get('slot') and 'example' in step:
            step['said'] = step.get('said') or str(step['example'])
            step['shape'] = shape(step.pop('example'))
        if step.get('options') and not all(str(o).isdigit() for o in step['options']):
            step.pop('options')   # numbers (a calendar's days) say nothing about anyone; names might
        out.append(step)
    return out


def masked(name, steps):
    """The request's words with each value that became a slot replaced by the slot's name: 「〈選ぶ項目1〉を開いて」.
    Takes generalize()'s steps and removes what they still say."""
    import unicodedata
    said = sorted({(s.pop('said'), s['slot']) for s in steps if s.get('said')}, key=lambda x: -len(x[0]))
    text = unicodedata.normalize('NFKC', name or '')
    for value, slot in said:
        chars = _norm(value)
        if len(chars) >= 2:   # the value as the request wrote it: any width, case or spacing
            text = re.sub(r'\s*'.join(re.escape(c) for c in chars), f'〈{slot}〉', text, flags=re.I)
    return text


def slot_name(element):
    """What the field is called on the page: the slot's name and the model's hint for the value."""
    if element.get('tag') == 'SELECT':   # a select's accessible name is its option text ("6時 7時 8時…"): the field's own name says what it is
        return (element.get('name_attr') or element.get('id') or (element.get('name') or '').split(' ')[0] or 'select')[:40]
    return (element.get('name') or element.get('name_attr') or element.get('id') or element.get('role') or 'field')[:40]


# ---- recording (called by browser_recipes.after_action) ------------------------

def record_step(run, action, params, pre, post):
    """Keep a non-login step with its value; returns True when kept."""
    steps = run.setdefault('flow_steps', [])
    if enabled() and action == 'back' and steps:
        # 「戻る」 undoes the step that led away: a detour is not part of the procedure. Kept, it sent every replay to a dead
        # end (2026-09-24, Yahoo!乗換案内: the site header's web-search button pressed by mistake, then back, then the
        # right button; the replay pressed the wrong one each time).
        steps.pop()
        return True
    if not enabled() or action not in ('type', 'select', 'fill_form', 'click', 'keyboard_press'):
        return False
    if len(steps) >= MAX_STEPS:
        return False
    on_login = recipes.login_like(pre) or recipes.login_like(post)   # values typed while logging in (IDs) are the login recipe's business; clicks there are navigation
    by_ref = {e['ref']: e for e in pre['elements']}
    entries = []
    if action == 'fill_form':
        for field in params.get('fields') or []:
            element = by_ref.get('@'+str(field.get('ref', '')).lstrip('@'))
            if element: entries.append(('type', element, str(field.get('value', ''))))
    elif action in ('type', 'select'):
        element = by_ref.get('@'+str(params.get('ref', '')).lstrip('@'))
        if element: entries.append((action, element, str(params.get('text') if action == 'type' else params.get('value'))))
    elif action == 'click':
        element = by_ref.get('@'+str(params.get('ref', '')).lstrip('@'))
        if element and element.get('role') == 'button' and element.get('form', -1) >= 0 and not on_login:
            # Sending a form sends what its fields hold. A field the site filled in itself (the departure from the last
            # search) was never typed, so the replay in a fresh browser sent it empty and stopped at 「出発地を入力してください」.
            # id and name together: a site may give two fields one id (Yahoo!乗換案内: from and to are both id=query_input)
            typed = {((s['targets'].get('ref') or {}).get('id'), (s['targets'].get('ref') or {}).get('name_attr')) for s in steps if s['action'] == 'type'}
            for field in pre['elements']:
                if (field.get('form') == element['form'] and field.get('value') and field.get('role') in ('textbox', 'searchbox')
                        and (field.get('id'), field.get('name_attr')) not in typed and not SECRET_LABEL.search(slot_name(field))):
                    entries.append(('type', field, field['value']))
        if element: entries.append(('click', element, None))
    elif action == 'keyboard_press':
        entries.append(('keyboard_press', None, params.get('key')))
    for kind, element, value in entries:
        if element is not None and (element.get('type') == 'password' or SECRET_LABEL.search(slot_name(element))):
            return False   # a secret typed by hand is never remembered; the login machinery covers it
        if on_login and kind != 'click':
            return False
        step = {'action': kind, 'targets': {'ref': recipes.descriptor(element, pre['elements'])} if element is not None else {},
                'pre': recipes.url_key(pre['url']), 'pre_landmarks': recipes.landmarks(pre),
                'post': {'key': recipes.url_key(post['url']), 'landmarks': recipes.landmarks(post)}}
        if kind in ('type', 'select'): step['slot'], step['example'] = slot_name(element), value[:200]
        if kind == 'click':
            step['siblings'] = sum(1 for e in pre['elements'] if e.get('role') == element.get('role') and e.get('name') and not e.get('disabled'))
            group = pick_group(element, pre['elements'])
            if group:   # the value is the name that was clicked; replay clicks the name asked for
                picks = sum(1 for x in steps if x.get('pick'))+1
                step['slot'], step['example'], step['pick'], step['options'] = f'選択{picks}', element['name'], True, group[:40]
        if not run.get('login_over'): step['recipe_index'] = len(run['steps'])   # where the login recorder would file it: dropped when a login recipe covers it
        if kind == 'keyboard_press': step['key'] = value
        if kind == 'type' and params.get('press_enter'): step['press_enter'] = True
        steps.append(step)
    return bool(entries)


def note_observation(run, post):
    """A read after actions on the same host: the flow may have reached its goal."""
    steps = run.get('flow_steps') or []
    if steps:
        run['flow_end'] = {'key': recipes.url_key(post['url']), 'landmarks': recipes.landmarks(post), 'at': time.time()}


def save_flow(run, name=''):
    """Save the run's recorded steps as a flow, when it ended in reading and has enough steps. Returns the flow or None."""
    steps = run.get('flow_steps') or []
    if run.get('saved') is not None:   # a login recipe was saved up to this index: those steps (and the OTP page after them) are the login, not the task
        steps = [s for s in steps if s.get('recipe_index') is None or s['recipe_index'] > run['saved']]
    end = run.get('flow_end')
    if not enabled() or len(steps) < MIN_STEPS or not end or run.get('unrecordable'):
        return None
    host = (steps[0]['pre'].split('/')[0] if steps else '') or ''
    if not host: return None
    steps = generalize(steps, name)
    name = masked(name, steps)
    slots = {s['slot']: s.get('shape', '') for s in steps if s.get('slot')}
    signature = hashlib.sha1(json.dumps([(s['action'], s.get('slot'), s.get('targets')) for s in steps], sort_keys=True).encode()).hexdigest()[:12]
    flows = flows_for(host)
    previous = run.get('flow_saved')
    if previous == signature:
        return next((f for f in flows if f['id'] == signature), None)   # this run already saved exactly this
    if previous:
        # The model reads pages between its steps, so this run was saved before it was finished: the longer version replaces
        # the shorter one (only what this run itself created and nothing has used since).
        flows = [f for f in flows if not (f['id'] == previous and f.get('successes', 0) <= 1 and not f.get('failures'))]
    for flow in flows:
        if flow['id'] == signature:
            flow['successes'] = flow.get('successes', 0)+1; flow['used'] = time.time()
            if name and not flow.get('name'): flow['name'] = name[:200]
            _write_flows(_host_file(host), flows); run['flow_saved'] = signature
            return flow
    flow = {'id': signature, 'host': host, 'start': run.get('landing') or steps[0]['pre'], 'name': name[:200], **({'kind': run['kind']} if run.get('kind') else {}),
            'steps': steps, 'slots': slots, 'end': {'key': end['key'], 'landmarks': end['landmarks']},
            'successes': 1, 'failures': 0, 'created': time.time(), 'used': time.time()}
    for old in flows:
        # The same task on this site, done again by hand after its replay failed: the new recording is the memory now.
        if old.get('failures') and not old.get('disabled') and (old.get('name') == flow['name'] or set(old.get('slots', {})) == set(slots)):
            old['disabled'] = True; old['superseded_by'] = signature
    flows.append(flow)
    _write_flows(_host_file(host), flows[-30:])
    run['flow_saved'] = signature
    return flow


def report(flow, success):
    """Counts only. A failed replay is handed back to the model, which does the task by hand; that fresh recording
    supersedes this flow (save_flow). Disabling by count left the memory dead with nothing to replace it."""
    flows = flows_for(flow['host'])
    for f in flows:
        if f['id'] == flow['id']:
            f['successes' if success else 'failures'] = f.get('successes' if success else 'failures', 0)+1
            f['used'] = time.time()
    _write_flows(_host_file(flow['host']), flows)


def describe(flow):
    """What the backend model reads to decide whether a remembered operation fits a request: the site, what was done
    (the task's first sentence, the pages' titles), the inputs it takes, and how it ended. Short: the model chose a fresh
    job over a fitting flow when this was the whole task text (2026-09-22 18:34)."""
    options = {s['slot']: s.get('options') or [] for s in flow['steps'] if s.get('pick')}
    shaped = {s['slot'] for s in flow['steps'] if s.get('slot') and 'shape' in s}
    named = {s['slot'] for s in flow['steps'] if s.get('named')}
    slots = ', '.join(f'{k}（' + ('依頼で名指しされた一覧の項目名' if k in named else f'形: {v}' if k in shaped else f'例: {v}')
                      + (f'。候補: {"/".join(options[k][:12])}…' if options.get(k) else '') + '）' for k, v in flow.get('slots', {}).items()) or '入力なし'
    name = re.split(r'[。\n]', flow.get('name') or '')[0][:60] or '（名前なし）'
    clicks = [((s['targets'].get('ref') or {}).get('name') or '')[:12] for s in flow['steps'] if s['action'] == 'click' and not s.get('pick') and s.get('targets')]
    path = '→'.join(c for c in clicks if c)[:80]
    return (f"[{flow['id']}] {flow['host']}: {name} / 押す: {path or 'なし'} / 入力: {slots} / {len(flow['steps'])}手"
            f" / 成功{flow.get('successes', 0)}回 失敗{flow.get('failures', 0)}回")


# ---- replay -----------------------------------------------------------------

async def run(flow, values, page=None):
    """Replay a flow with new values; returns {'replayed': bool, 'reason', 'completed_steps', 'elapsed_ms'} and leaves the
    browser on the end page (the caller reads it). Values missing for a slot keep the recorded example."""
    missing = sorted({s['slot'] for s in flow['steps'] if s.get('slot') and 'example' not in s and values.get(s['slot']) in (None, '')})
    if missing:   # a flow keeps no values: every slot's value comes from the request
        return {'replayed': False, 'reason': 'missing_values: ' + ', '.join(missing), 'completed_steps': [], 'elapsed_ms': 0}
    if flow.get('kind') == 'desktop':
        from app.services.desktop_control import replay
        result = await replay(flow, values)
        report(flow, result['replayed'])
        return result
    from app.agent.v2.tools import _execute_browser_tool
    from app.services.browser_replay import observe, resolve, rematch, attempt, STEP_WAIT_SECONDS, POLL_SECONDS
    from app.services.jev_decisions import Decisions
    from app.tools.browser import get_executor_page
    started = time.perf_counter()
    page = page or await get_executor_page()
    done, reason = [], None
    token = None
    try:
        # The opening is a normal open: the login memory (or the first login by code) takes the browser to the logged-in page.
        # Only the flow's own steps run under the replaying flag (so they are not recorded again).
        start = 'https://'+flow['start'] if not flow['start'].startswith('http') else flow['start']
        opened = await _execute_browser_tool('open_target', {'url': start, 'login': True, 'observation': 'dom'})
        if isinstance(opened, dict) and opened.get('success') is False: raise RuntimeError('open_failed')
        token = recipes.replaying.set(True)
        snap = await observe(page)
        async with Decisions(os.environ.get('DAN_USER_ID'), max_calls=6) as decisions:
            for index, step in enumerate(flow['steps']):
                if step.get('pick') and values.get(step['slot']) not in (None, step.get('example')):
                    # a pick with a new value: the same kind of element, named by the value asked for
                    step = {**step, 'targets': {'ref': {**step['targets']['ref'], 'name': str(values[step['slot']])}}}
                find = (lambda s, st=step: pick_resolve(st, s)) if step.get('pick') else (lambda s, st=step: resolve(st, s))
                refs, deadline = (find(snap) if step.get('targets') else {}), time.perf_counter()+STEP_WAIT_SECONDS
                while refs is None and time.perf_counter() < deadline:
                    await page.wait_for_timeout(int(POLL_SECONDS*1000)); snap = await observe(page); refs = find(snap)
                if refs is None and index+1 < len(flow['steps']) and flow['steps'][index+1].get('targets') and resolve(flow['steps'][index+1], snap):
                    done.append('skipped '+step['action']); continue   # a step the site did not need today (a login click when the session was still alive)
                if refs is None:
                    refs = await rematch(step, snap, decisions)
                if step['action'] == 'click':
                    from app.services import command_job_tools as gate
                    try: target = await gate.browser_target(refs)
                    except Exception: raise RuntimeError('page_changed_before_action')
                    if gate.needs_confirmation(target):
                        # The same gate as the login replay: purchases, cancellations, sends are never committed by a replay.
                        # The browser stays on this page; the model (and the owner) take it from here.
                        raise RuntimeError('sensitive_action_needs_agent: '+(target.get('label') or '')[:40])
                    outcome = await attempt(_execute_browser_tool, 'click', {**refs, 'observation': 'dom', 'login': False, 'replay': False}, page)
                elif step['action'] == 'type':
                    value = values.get(step['slot']) or step.get('example', '')
                    outcome = await _execute_browser_tool('type', {**refs, 'text': str(value), 'press_enter': bool(step.get('press_enter')), 'observation': 'dom'})
                elif step['action'] == 'select':
                    value = values.get(step['slot']) or step.get('example', '')
                    outcome = await _execute_browser_tool('select', {**refs, 'value': str(value), 'observation': 'dom'})
                elif step['action'] == 'keyboard_press':
                    outcome = await _execute_browser_tool('keyboard_press', {'key': step.get('key') or 'Enter', 'observation': 'dom'})
                else:
                    outcome = await _execute_browser_tool(step['action'], {**refs, **step.get('params', {}), 'observation': 'dom'})
                if isinstance(outcome, dict) and outcome.get('success') is False:
                    raise RuntimeError('step_failed: '+str(outcome.get('error') or '')[:120])
                done.append(step['action']+(' '+step['slot'] if step.get('slot') else ''))
                snap = await observe(page)
            deadline = time.perf_counter()+15
            def reached(s):
                marks = set(recipes.landmarks(s)); target = set(flow['end'].get('landmarks') or [])
                return recipes.url_key(s['url']) == flow['end']['key'] or (bool(target) and len(marks & target)/max(1, len(marks | target)) >= .5)
            while not reached(snap) and time.perf_counter() < deadline:
                await page.wait_for_timeout(int(POLL_SECONDS*1000)); snap = await observe(page)
            if not reached(snap): raise RuntimeError('end_page_not_reached')
    except Exception as exc:
        reason = str(exc)[:160]
    finally:
        if token is not None: recipes.replaying.reset(token)
    report(flow, reason is None)
    from app.tools.browser_metrics import record_timing
    record_timing('workflow', 'browser_flows', (time.perf_counter()-started)*1000, 'handoff' if reason else 'verified', {'tool_calls': len(done), 'reason': reason or ''})
    return {'replayed': reason is None, 'reason': reason, 'completed_steps': done, 'elapsed_ms': round((time.perf_counter()-started)*1000)}


def matches(names, want):
    """Which of these names is the item asked for: the same name, else the one name that contains it (a list shows
    「本田様（4人）」 for 「本田様」). Returns the index or None."""
    want = _norm(want)
    if not want:
        return None
    exact = [i for i, n in enumerate(names) if _norm(n) == want]
    if len(exact) == 1:
        return exact[0]
    inside = [i for i, n in enumerate(names) if want in _norm(n)]
    return inside[0] if len(inside) == 1 else None


def pick_resolve(step, snap):
    """A pick: among elements of the recorded kind, the one named by the value asked for."""
    want = step['targets']['ref']
    items = [e for e in snap['elements'] if not e['disabled'] and e['role'] == want['role'] and e.get('tag') == want.get('tag')]
    index = matches([e['name'] for e in items], want['name'])
    return None if index is None else {'ref': items[index]['ref']}


TOOL = {
    'name': 'flow',
    'description': ('一度やったブラウザやデスクトップアプリ（host が desktop: のもの）の手順の記憶。action=list: 知っている手順（入力の穴つき）を一覧する／action=replay: id と values（穴→値）で、'
                    '大きいモデルなしに手順を再生してその結果の画面で止める（続けて browser read / desktop read で読む）。記憶に値は残っていないので、穴の値は全部依頼から渡す。'
                    '同じサイトで同じ種類の作業を頼まれたら、まず list を見て、合う手順があれば replay を使う。合わなければ通常どおり操作する（成功すれば自動で記憶される）。'),
    'input_schema': {'type': 'object', 'properties': {
        'action': {'type': 'string', 'enum': ['list', 'replay']},
        'host': {'type': 'string', 'description': 'list を絞るホスト（省略可）'},
        'id': {'type': 'string'}, 'values': {'type': 'object', 'additionalProperties': {'type': 'string'}},
    }, 'required': ['action'], 'additionalProperties': False},
}


async def tool(params):
    action = params.get('action')
    if action == 'list':
        flows = all_flows()
        if params.get('host'): flows = [f for f in flows if params['host'] in f['host']]
        return {'success': True, 'output': '\n'.join(describe(f) for f in flows[:40]) or '記憶している手順はまだありません。'}
    if action == 'replay':
        flow = next((f for f in all_flows() if f['id'] == params.get('id')), None)
        if not flow: return {'success': False, 'error': 'その id の手順はありません（flow list で確認）'}
        result = await run(flow, params.get('values') or {})
        return {'success': result['replayed'], 'output': json.dumps(result, ensure_ascii=False), **({} if result['replayed'] else {'error': result['reason']})}
    return {'success': False, 'error': 'action は list か replay'}
