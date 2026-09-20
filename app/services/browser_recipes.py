"""Operation memory: record successful browser runs, keep them as recipes.

Dan used to operate every site as if seeing it for the first time. This layer
remembers *how* a login was done (which element, which action, which page came
next) so the next visit can be replayed by code (see browser_replay).

Never stored: typed text, credentials, OTP/TOTP codes, page body, screenshots.
Stored: action names, non-secret parameters, element role/label, URL host+path.
A recorder failure must never break the browser tool; callers swallow errors.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import contextvars
import logging
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

AUTH = {'fill_credential', 'fill_totp_code', 'wait_for_otp_from_app', 'wait_for_link_from_app', 'solve_captcha'}
# Steps code can repeat without a model writing a string for them.
REPLAYABLE = AUTH | {'click', 'keyboard_press', 'wait_for'}
OBSERVE_ONLY = {'screenshot', 'content', 'hover', 'scroll'}
SESSION_CONTROL = {'session_status', 'hold', 'release', 'close'}
REF_KEYS = ('ref', 'image_ref', 'input_ref')
SAFE_PARAMS = {
    'click': (), 'keyboard_press': ('key',), 'wait_for': ('expect',),
    'fill_credential': ('field', 'service', 'url', 'press_enter'),
    'fill_totp_code': ('service', 'url', 'press_enter'),
    'wait_for_otp_from_app': ('service', 'source', 'email_address', 'timeout_seconds', 'press_enter'),
    'wait_for_link_from_app': ('service', 'source', 'email_address', 'timeout_seconds'),
    'solve_captcha': ('image_selector', 'input_selector'),
}
MAX_STEPS = 24
MAX_VARIANTS = 3
RUN_IDLE_SECONDS = 900

replaying = contextvars.ContextVar('dan_browser_replaying', default=False)

# Read-only metadata over elements the observation already tagged.
SNAPSHOT = r"""() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const vis = e => {const r=e.getBoundingClientRect(),s=getComputedStyle(e);
    return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'};
  const role = e => e.getAttribute('role') || ({BUTTON:'button',A:'link',TEXTAREA:'textbox',SELECT:'combobox'}[e.tagName]) ||
    (e.tagName === 'INPUT' ? (['submit','button','image'].includes(e.type) ? 'button' : e.type==='search'?'searchbox':
      ['checkbox','radio'].includes(e.type)?e.type:'textbox') : '');
  const name = e => norm(e.getAttribute('aria-label') ||
    (e.getAttribute('aria-labelledby') || '').split(/\s+/).map(id=>document.getElementById(id)?.textContent || '').join(' ') ||
    (e.labels && [...e.labels].map(l=>l.innerText).join(' ')) || e.innerText ||
    (e.tagName==='INPUT' && ['submit','button'].includes(e.type) ? e.value : '') || e.getAttribute('alt') || e.placeholder || '');
  const deep = s => window.__danDeep ? window.__danDeep(s) : [...document.querySelectorAll(s)];
  const elements = deep('[data-dan-ref]').filter(vis).slice(0, 400).map(e => ({
    ref:'@'+e.getAttribute('data-dan-ref'), role:role(e), name:name(e).slice(0,120), tag:e.tagName,
    type:e.type || '', id:e.id || '', name_attr:e.getAttribute('name') || '', disabled:!!e.disabled}));
  return {url:location.href, password:deep('input[type="password"]').some(vis), elements};
}"""


def enabled():
    return os.environ.get('DAN_BROWSER_REPLAY', '1') != '0'


def root():
    path = Path(os.environ.get('DAN_BROWSER_RECIPES_DIR') or Path.home()/'.dan'/'browser-recipes')
    path.mkdir(parents=True, exist_ok=True)
    return path


def url_key(url):
    """host+path; opaque ids generalised so a session token does not split recipes."""
    parts = urlsplit(url or '')
    segments = ['*' if re.fullmatch(r'[0-9a-fA-F-]{16,}|\d{6,}', s) else s for s in parts.path.split('/')]
    return (parts.hostname or '')+'/'.join(segments).rstrip('/')


def login_like(snapshot):
    from app.agent.v2.tools import _looks_like_login_url
    return bool(snapshot.get('password')) or _looks_like_login_url(snapshot.get('url') or '')


def landmarks(snapshot):
    """Hashed role|label set: enough to recognise a page, not to read it."""
    marks = {hashlib.sha1((e['role']+'|'+e['name']).encode('utf-8')).hexdigest()[:12]
             for e in snapshot.get('elements', []) if e['name'] and e['role'] in {'link', 'button'}}
    return sorted(marks)[:80]


def descriptor(element, elements=()):
    found = {k: element[k] for k in ('role', 'name', 'tag', 'type', 'id', 'name_attr')}
    # Header and footer often repeat a link. Which of the twins was used is part of its identity.
    twins = [e for e in elements if not e['disabled'] and all(e[k] == element[k] for k in ('role', 'name', 'type', 'id', 'name_attr'))]
    if len(twins) > 1 and element in twins:
        found['nth'], found['of'] = twins.index(element), len(twins)
    return found


async def snapshot(page):
    result = await page.evaluate(SNAPSHOT)
    return result if isinstance(result, dict) else {'url': page.url, 'password': False, 'elements': []}


# ---- storage -------------------------------------------------------------

def _read(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def _write(path, data):
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(temp, path)


def _host_file(host):
    return root()/(re.sub(r'[^A-Za-z0-9.-]', '_', host or 'unknown')+'.json')


def _run_file():
    from app.tools.browser import _browser_room_id
    runs = root()/'runs'
    runs.mkdir(exist_ok=True)
    return runs/(re.sub(r'[^A-Za-z0-9-]', '_', _browser_room_id() or 'default')+'.json')


def recipes_for(host):
    return _read(_host_file(host), [])


def find(landing_key):
    """Enabled recipes whose login page is the page we just landed on."""
    host = landing_key.split('/')[0]
    return [r for r in recipes_for(host) if r.get('enabled', True) and r['landing'] == landing_key]


def signature(steps):
    parts = [[s['action'], sorted((k, d['role'], d['name']) for k, d in s.get('targets', {}).items())] for s in steps]
    return hashlib.sha1(json.dumps(parts, ensure_ascii=False).encode('utf-8')).hexdigest()[:16]


def save_recipe(run, end_index):
    steps = run['steps'][:end_index+1]
    end = steps[-1]['post']
    recipe = {'id': run['id'], 'landing': run['landing'], 'start_url': run['start_url'],
              'steps': [{k: s[k] for k in ('action', 'params', 'targets', 'pre')} for s in steps],
              'end': {'key': end['key'], 'landmarks': end['landmarks']},
              'login_pages': sorted({s['pre'] for s in steps}),
              'auth_landmarks': [s for s in steps if s['action'] in AUTH][-1]['pre_landmarks'],
              'signature': signature(steps), 'created': time.time(), 'enabled': True,
              'uses': 0, 'successes': 0, 'consecutive_failures': 0, 'last_elapsed_ms': None}
    host = run['landing'].split('/')[0]
    existing = recipes_for(host)
    same = [r for r in existing if r['landing'] == recipe['landing']]
    others = [r for r in existing if r['landing'] != recipe['landing']]
    for old in same:
        if old['id'] == recipe['id'] or old['signature'] == recipe['signature']:
            # Same procedure observed again: refresh it, keep its track record.
            recipe.update({k: old[k] for k in ('uses', 'successes', 'last_elapsed_ms')})
    same = [r for r in same if r['id'] != recipe['id'] and r['signature'] != recipe['signature']]
    _write(_host_file(host), others+([recipe]+same)[:MAX_VARIANTS])
    return recipe


def report(recipe, success, elapsed_ms):
    """Two consecutive failures mean the site changed; the next manual login re-records."""
    host = recipe['landing'].split('/')[0]
    existing = recipes_for(host)
    for item in existing:
        if item['id'] == recipe['id']:
            item['uses'] += 1
            item['successes'] += int(success)
            item['consecutive_failures'] = 0 if success else item['consecutive_failures']+1
            item['enabled'] = item['consecutive_failures'] < 2
            if success:
                item['last_elapsed_ms'] = elapsed_ms
    _write(_host_file(host), existing)


# ---- telling the model that a login is already remembered ----------------
# Observed: Dan looked up credentials, then opened a login URL from its own notes
# that no longer existed (17s lost), although a working entrance was remembered.

def entry_hint(*places):
    """One sentence for the first place (URL or bare host) that has a remembered login."""
    try:
        if not enabled():
            return None
        for place in places:
            if not place:
                continue
            text = str(place)
            host = urlsplit(text if '//' in text else '//'+text).hostname
            known = [r for r in recipes_for(host) if r.get('enabled', True) and r.get('start_url')] if host else []
            if known:
                best = max(known, key=lambda r: (r.get('successes', 0), r.get('created', 0)))
                return ('このサイトはログイン手順を記憶済み。ログインが必要なら browser(action="open_target", url="'+best['start_url']+
                        '") を開くだけで、ID・パスワード・確認コードの入力まで自動で再生される'
                        '（認証情報を取り直したり、別のログインURLを探したりしなくてよい）。')
    except Exception:
        logger.debug('entry hint unavailable', exc_info=True)
    return None


# ---- how long a site needs before its URL can be trusted ------------------
# open_target waits ~6s after load because some sites (Apple) bounce to a login
# page by script well after the DOM is ready. Most sites never do. Remember per
# host what actually happened instead of charging every open the worst case.
SETTLE_DEFAULT_POLLS = 30      # x200ms = 6s: unknown hosts and hosts that have bounced
SETTLE_TRUSTED_POLLS = 8       # 1.6s: hosts opened repeatedly without a single late bounce
SETTLE_TRUST_AFTER = 3


def _never_break_the_browser(function):
    def safe(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception:
            logger.debug('settle memory unavailable', exc_info=True)
            return SETTLE_DEFAULT_POLLS if function.__name__ == 'settle_polls' else None
    return safe


def _settle_file():
    return root()/'settle.json'


@_never_break_the_browser
def settle_polls(url):
    if not enabled():
        return SETTLE_DEFAULT_POLLS
    seen = _read(_settle_file(), {}).get(urlsplit(url or '').hostname or '')
    if seen and seen['late'] == 0 and seen['full_waits'] >= SETTLE_TRUST_AFTER:
        return SETTLE_TRUSTED_POLLS
    return SETTLE_DEFAULT_POLLS


@_never_break_the_browser
def record_settle(url, polls_waited, bounced_late):
    """Only a full-length wait proves "no late bounce"; a shortened one proves nothing."""
    host = urlsplit(url or '').hostname
    if not host or not enabled():
        return
    data = _read(_settle_file(), {})
    seen = data.setdefault(host, {'full_waits': 0, 'late': 0})
    if bounced_late:
        seen['late'] += 1
    elif polls_waited >= SETTLE_DEFAULT_POLLS:
        seen['full_waits'] += 1
    else:
        return
    _write(_settle_file(), data)


@_never_break_the_browser
def distrust(url):
    """A click got thrown onto a login page: this host's quiet URL was not proof. Back to the full wait."""
    host = urlsplit(url or '').hostname
    if host and enabled():
        data = _read(_settle_file(), {})
        data.setdefault(host, {'full_waits': 0, 'late': 0})['late'] += 1
        _write(_settle_file(), data)


# ---- recording -----------------------------------------------------------

async def around(action, params, execute):
    """The browser tool's single entry point passes through here."""
    pre, url_before = None, None
    try:
        pre = await before_action(action, params)
        if action == 'click' and enabled() and not replaying.get():
            from app.tools.browser import get_executor_page
            url_before = url_key((await get_executor_page()).url or '')
    except Exception:
        logger.debug('browser recipe pre-snapshot failed', exc_info=True)
    result = await execute(action, params)
    try:
        await after_action(action, params, result, pre)
    except Exception:
        logger.debug('browser recipe recording failed', exc_info=True)
    if action in {'open_target', 'click'} and not (isinstance(result, dict) and result.get('success') is False):
        try:
            from app.services.browser_replay import maybe_replay
            if action == 'open_target':
                before = result
            if action == 'click':
                # Dan often reaches the login page through a "ログイン" link, not by URL.
                # Only an arrival counts: a click that stays on the page is Dan's own work.
                from app.tools.browser import get_executor_page
                if url_before is None or url_key((await get_executor_page()).url or '') == url_before:
                    return result
            result = await maybe_replay(params, result)
            if action == 'open_target' and result is before and isinstance(result, dict) and isinstance(result.get('content'), list):
                # Opened some other page of a site whose login is remembered (or a dead URL).
                hint = entry_hint(params.get('url'))
                if hint and hint.split('url="')[1].split('"')[0] != params.get('url'):
                    result['content'].append({'type': 'text', 'text': hint})
        except Exception:
            logger.warning('browser replay unavailable', exc_info=True)
    return result


async def _username_step(page, params, pre):
    """A typed login ID becomes a credential step, so the ID itself is never stored."""
    text = params.get('text')
    if not isinstance(text, str) or not text or not login_like(pre):
        return None
    from app.services.credentials_service import get_credentials_service, narrow_url_matches
    user_id = os.environ.get('DAN_USER_ID', '00000000-0000-0000-0000-000000000001')
    matches = narrow_url_matches(await get_credentials_service().find_credentials_by_url(user_id, pre['url']))
    hits = [m for m in matches if m.get('id') == text]
    if len(hits) != 1:
        return None
    return 'fill_credential', {'field': 'username', 'url': pre['url'], 'service': hits[0].get('service'),
                               'press_enter': bool(params.get('press_enter', False))}


async def before_action(action, params):
    """Element identity must be captured before the action can replace the page."""
    if not enabled() or replaying.get() or action in SESSION_CONTROL or action in {'open', 'open_target'}:
        return None
    if action in OBSERVE_ONLY or not _run_file().exists():
        return None  # nothing to identify; keeps ordinary browsing free of extra work
    from app.tools.browser import get_executor_page
    page = await get_executor_page()
    return await snapshot(page)


async def after_action(action, params, result, pre):
    if not enabled() or replaying.get() or action in SESSION_CONTROL:
        return
    path = _run_file()
    if action not in {'open', 'open_target'} and not path.exists():
        return
    from app.tools.browser import get_executor_page
    page = await get_executor_page()
    if action in OBSERVE_ONLY or (isinstance(result, dict) and result.get('success') is False):
        # A look (or a step without effect) still shows where the previous step
        # really ended: sites navigate after the tool call has already returned.
        run = _read(path, None)
        if run and run['steps']:
            _settle(run, await snapshot(page))
            _write(path, run)
        return
    if action in {'open', 'open_target'}:
        post = await snapshot(page)
        _write(path, {'id': hashlib.sha1(os.urandom(16)).hexdigest()[:12], 'start_url': params.get('url'),
                      'landing': url_key(post['url']), 'started': time.time(), 'updated': time.time(),
                      'steps': [], 'saved': None})
        return
    run = _read(path, None)
    if not run or pre is None or time.time()-run['updated'] > RUN_IDLE_SECONDS:
        return
    _settle(run, pre)
    post = await snapshot(page)
    if action == 'type':
        converted = await _username_step(page, params, pre)
        if converted:
            action, safe = converted
        else:
            action = None
    elif action in REPLAYABLE:
        safe = {k: params[k] for k in SAFE_PARAMS[action] if params.get(k) is not None}
    else:
        # evaluate etc. that did not move the page is a look, not a step.
        if url_key(post['url']) == url_key(pre['url']) and post['password'] == pre['password']:
            return
        action = None
    targets = {}
    if action:
        by_ref = {e['ref']: e for e in pre['elements']}
        for key in REF_KEYS:
            if params.get(key):
                element = by_ref.get('@'+str(params[key]).lstrip('@'))
                if not element:
                    action = None
                    break
                targets[key] = descriptor(element, pre['elements'])
        if action == 'click' and not targets:
            action = None  # coordinate clicks cannot be re-found
    if not action or len(run['steps']) >= MAX_STEPS:
        path.unlink(missing_ok=True)  # The rest needs a model; what was saved stays saved.
        return
    run['steps'].append({'action': action, 'params': safe, 'targets': targets, 'pre': url_key(pre['url']),
                         'pre_landmarks': landmarks(pre),
                         'post': {'key': url_key(post['url']), 'login_like': login_like(post), 'landmarks': landmarks(post)}})
    run['updated'] = time.time()
    _save_if_logged_in(run)
    _write(path, run)


def _settle(run, snap):
    """The state seen before the next call is the settled result of the last step."""
    if run['steps']:
        run['steps'][-1]['post'] = {'key': url_key(snap['url']), 'login_like': login_like(snap), 'landmarks': landmarks(snap)}
        _save_if_logged_in(run)


def _save_if_logged_in(run):
    end = _login_end(run['steps'])
    # Re-saved when a later auth step (OTP after password) extends the login.
    if end is not None and run.get('saved') != end:
        save_recipe(run, end)
        run['saved'] = end


def _login_end(steps):
    """Logged in = after the last auth step the page stopped asking AND moved on
    from the page where that step happened (an OTP page has no password field,
    yet the login is not over until its submit leaves it). Later navigation
    belongs to the task, not to the login."""
    auth = [i for i, s in enumerate(steps) if s['action'] in AUTH]
    keys = [(s['action'], json.dumps(s['targets'], sort_keys=True), s['pre']) for s in steps]
    if not auth or len(set(keys)) != len(keys):  # a repeated step is a retry loop, not a procedure
        return None
    origin = steps[auth[-1]]
    for i in range(auth[-1], len(steps)):
        post = steps[i]['post']
        before, after = set(origin['pre_landmarks']), set(post['landmarks'])
        moved = post['key'] != origin['pre'] or (len(before & after)/len(before | after) < .5 if before | after else False)
        if not post['login_like'] and moved:
            return i
    return None
