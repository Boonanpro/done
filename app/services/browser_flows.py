"""Operation memory beyond login: any sequence of browser steps the large model did once (open a site, fill a search
form, pick options, submit, read the result) is remembered as a FLOW with its typed values as slots, and replayed by
code next time with new values. First principles: never compute twice what does not change; the second time costs no
model call at all (a Jev choice at most, when an element moved).

Recording piggybacks on browser_recipes (every tool call already passes through it): here the run's non-login steps are
kept with their values, and a run that ended in reading a page (read/find/content/read_url) is saved as a flow.

    flow = {'id', 'host', 'start': url_key, 'name': task words, 'steps': [...], 'slots': {slot: example},
            'end': {'key', 'landmarks'}, 'successes', 'failures', 'created', 'used'}
    step = {'action': 'click'|'type'|'select'|'keyboard_press'|'fill_credential'..., 'params': {...}, 'targets': {...},
            'slot': 'label of the field' (type/select), 'pre': url_key, 'post': {...}}

Values of password fields, credential steps and one-time codes are never stored (the login machinery handles those).
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


def slot_name(element):
    """What the field is called on the page: the slot's name and the model's hint for the value."""
    if element.get('tag') == 'SELECT':   # a select's accessible name is its option text ("6時 7時 8時…"): the field's own name says what it is
        return (element.get('name_attr') or element.get('id') or (element.get('name') or '').split(' ')[0] or 'select')[:40]
    return (element.get('name') or element.get('name_attr') or element.get('id') or element.get('role') or 'field')[:40]


# ---- recording (called by browser_recipes.after_action) ------------------------

def record_step(run, action, params, pre, post):
    """Keep a non-login step with its value; returns True when kept."""
    if not enabled() or action not in ('type', 'select', 'fill_form', 'click', 'keyboard_press'):
        return False
    steps = run.setdefault('flow_steps', [])
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
    if not enabled() or len(steps) < MIN_STEPS or not end:
        return None
    host = (steps[0]['pre'].split('/')[0] if steps else '') or ''
    if not host: return None
    slots = {s['slot']: s['example'] for s in steps if s.get('slot')}
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
    flow = {'id': signature, 'host': host, 'start': run.get('landing') or steps[0]['pre'], 'name': name[:200],
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
    slots = ', '.join(f'{k}（例: {v}' + (f'。候補: {"/".join(options[k][:12])}…' if options.get(k) else '') + '）' for k, v in flow.get('slots', {}).items()) or '入力なし'
    name = re.split(r'[。\n]', flow.get('name') or '')[0][:60] or '（名前なし）'
    clicks = [((s['targets'].get('ref') or {}).get('name') or '')[:12] for s in flow['steps'] if s['action'] == 'click' and not s.get('pick') and s.get('targets')]
    path = '→'.join(c for c in clicks if c)[:80]
    return (f"[{flow['id']}] {flow['host']}: {name} / 押す: {path or 'なし'} / 入力: {slots} / {len(flow['steps'])}手"
            f" / 成功{flow.get('successes', 0)}回 失敗{flow.get('failures', 0)}回")


# ---- replay -----------------------------------------------------------------

async def run(flow, values, page=None):
    """Replay a flow with new values; returns {'replayed': bool, 'reason', 'completed_steps', 'elapsed_ms'} and leaves the
    browser on the end page (the caller reads it). Values missing for a slot keep the recorded example."""
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
                refs, deadline = (resolve(step, snap) if step.get('targets') else {}), time.perf_counter()+STEP_WAIT_SECONDS
                while refs is None and time.perf_counter() < deadline:
                    await page.wait_for_timeout(int(POLL_SECONDS*1000)); snap = await observe(page); refs = resolve(step, snap)
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
                    value = values.get(step['slot'], step.get('example', ''))
                    outcome = await _execute_browser_tool('type', {**refs, 'text': str(value), 'press_enter': bool(step.get('press_enter')), 'observation': 'dom'})
                elif step['action'] == 'select':
                    value = values.get(step['slot'], step.get('example', ''))
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


TOOL = {
    'name': 'flow',
    'description': ('一度やったブラウザの手順の記憶。action=list: 知っている手順（入力の穴つき）を一覧する／action=replay: id と values（穴→値）で、'
                    '大きいモデルなしに手順を再生してその結果のページで止める（続けて browser read で読む）。'
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
