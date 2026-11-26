"""When the owner last used Dan's screens: one file's time, so any process can read it (envato_shelf's renders).

After Effects renders at nice 15 still took the whole Mac: on 2026-11-27 one render of an Envato part stopped the
editor's media for 80〜105 seconds and the sandbox answered nothing until it ended. As macOS background work
(taskpolicy -b) the same render never held a read over 0.35 s, but took 7 times as long (941 s instead of 138 s).
So a render goes background only while the owner is using the screens, and at full speed otherwise.

touch() is called for every request from outside this Mac (the sandbox, the core and the home media entrance).
"""
import os
import time
from pathlib import Path

STAMP = Path(os.environ.get('DAN_OWNER_ACTIVE_FILE') or Path.home() / '.dan' / 'owner-active')
EVERY = 5.0
_last = [0.0]


def touch(now=None):
    now = time.time() if now is None else now
    if now - _last[0] < EVERY:
        return
    _last[0] = now
    try:
        STAMP.parent.mkdir(parents=True, exist_ok=True)
        STAMP.touch()
        os.utime(STAMP, (now, now))
    except OSError:
        pass


def recent(seconds=120, now=None):
    now = time.time() if now is None else now
    try:
        return now - STAMP.stat().st_mtime < seconds
    except OSError:
        return False


LOCAL = {'127.0.0.1', '::1', 'localhost', None}


def from_outside(scope):
    """A request that came from the owner's device: not one Dan's own processes make on this Mac."""
    client = scope.get('client')
    host = client[0] if client else None
    if host not in LOCAL:
        return True
    headers = dict(scope.get('headers') or [])
    return bool(headers.get(b'cf-connecting-ip') or headers.get(b'x-forwarded-for'))


class Middleware:
    """ASGI: stamps the owner's activity, adds nothing to the request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') in ('http', 'websocket') and from_outside(scope):
            touch()
        return await self.app(scope, receive, send)
