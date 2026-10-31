"""Serialize tool operations that share an executor, including voice tool hosts."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import os
from pathlib import Path
import time

ROOT = Path.home() / '.dan' / 'browser-operation-locks'
TOOLS = {'browser', 'browser_plan', 'browser_flow', 'browser_script'}

class BrowserBusy(Exception):
    pass


@asynccontextmanager
async def operation(tool, timeout=None):
    room = os.environ.get('DAN_BROWSER_ROOM')
    if tool not in TOOLS or not room:
        yield
        return
    from app.services.file_lock import lock
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / (hashlib.sha256(room.encode()).hexdigest() + '.lock')
    if timeout is None:
        timeout = .8 if os.environ.get('DAN_TOOL_HOST') else 240
    with path.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                handle.seek(0); lock(handle.fileno(), True)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise BrowserBusy('表示中のブラウザは別の操作中です。今回の操作は実行していません。')
                await asyncio.sleep(.02)
        try:
            yield
        finally:
            handle.seek(0); lock(handle.fileno(), False)
