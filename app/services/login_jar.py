"""One login state per user, shared by all of Dan's browsers (every room and every job).

Each room's browser used to copy the login cookies once, when its profile was first made, from an old "master" browser
that is seldom used now; a login made later in one room never reached the others. So a job's browser often met a site
logged out, and logging in from a fresh browser drew bot checks: on 2026-09-30 a top-up job stopped 22 minutes on an
hCaptcha that the owner's own, logged-in Chrome never showed.

Now the core, which owns every Dan browser, keeps a per-user jar (encrypted on disk) and syncs it over each browser's
own control port (CDP at the browser level: no page is attached or touched):
  absorb(port, user)  the browser's cookies go into the jar (newer replaces older, by name/domain/path)
  apply(port, user)   the jar's live cookies go into the browser
On every "ensure" (a job or a room starting to use its browser) the browser is absorbed first and then given the jar;
before a browser is closed (by request or for being idle) it is absorbed. A login made anywhere is then everyone's.
"""
import asyncio
import json
import logging
import threading
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path.home() / '.dan' / 'logins'
_lock = threading.Lock()


def _file(user_id):
    return ROOT / f'{user_id}.jar'


def _crypt():
    from app.services.encryption import EncryptionService
    return EncryptionService()


def _load(user_id):
    path = _file(user_id)
    if not path.exists():
        return {}
    try:
        return json.loads(_crypt().decrypt(path.read_bytes()))
    except Exception:
        logger.exception('login jar unreadable for %s; starting empty', user_id)
        return {}


def _save(user_id, jar):
    ROOT.mkdir(parents=True, exist_ok=True)
    temp = _file(user_id).with_suffix('.tmp')
    temp.write_bytes(_crypt().encrypt(json.dumps(jar, ensure_ascii=False)))
    temp.replace(_file(user_id))


def _key(cookie):
    return f"{cookie.get('name')}|{cookie.get('domain')}|{cookie.get('path', '/')}"


def _live(cookie, now):
    expires = cookie.get('expires')
    return not (isinstance(expires, (int, float)) and 0 < expires < now)


async def _cdp(port, method, params=None):
    import websockets
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f'http://127.0.0.1:{port}/json/version', timeout=3) as resp:
        ws_url = json.loads(resp.read())['webSocketDebuggerUrl']
    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024, open_timeout=5, close_timeout=2) as ws:
        await ws.send(json.dumps({'id': 1, 'method': method, 'params': params or {}}))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if msg.get('id') == 1:
                if 'error' in msg:
                    raise RuntimeError(str(msg['error'])[:200])
                return msg.get('result', {})


def absorb(port, user_id):
    """The browser's cookies into the user's jar. Returns how many it held."""
    if not port or not user_id:
        return 0
    cookies = asyncio.run(_cdp(port, 'Storage.getCookies')).get('cookies', [])
    now = time.time()
    with _lock:
        jar = _load(user_id)
        for cookie in cookies:
            if _live(cookie, now):
                jar[_key(cookie)] = {**cookie, 'seen': now}
        jar = {k: c for k, c in jar.items() if _live(c, now)}
        _save(user_id, jar)
    return len(cookies)


def apply(port, user_id):
    """The jar's live cookies into the browser. Returns how many were set."""
    if not port or not user_id:
        return 0
    now = time.time()
    with _lock:
        jar = _load(user_id)
    cookies = []
    for c in jar.values():
        if not _live(c, now):
            continue
        cookie = {k: c[k] for k in ('name', 'value', 'domain', 'path', 'secure', 'httpOnly', 'sameSite', 'expires', 'priority',
                                     'sameParty', 'sourceScheme', 'sourcePort', 'partitionKey') if k in c}
        if isinstance(cookie.get('expires'), (int, float)) and cookie['expires'] <= 0:
            cookie.pop('expires')   # a session cookie
        cookies.append(cookie)
    if cookies:
        asyncio.run(_cdp(port, 'Storage.setCookies', {'cookies': cookies}))
    return len(cookies)


def sync(port, user_id, reason=''):
    """Absorb then apply, never failing the caller (a missing login only means logging in again)."""
    from app.tools.browser import _write_browser_recovery_log
    try:
        held = absorb(port, user_id)
        given = apply(port, user_id)
        _write_browser_recovery_log('login_jar_sync', port=port, absorbed=held, applied=given, reason=reason)
    except Exception as exc:
        _write_browser_recovery_log('login_jar_sync_failed', port=port, error=str(exc)[:200], reason=reason)
