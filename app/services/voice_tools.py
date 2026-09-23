"""The voice backend's access to Dan's whole tool set: a tool_host process per owner and room, started on first use and
closed when idle. The backend reaches every tool the way chat Dan does, disclosed in steps (dan_tools): a catalog in its
instructions, dan_tool_help, dan_tool.

A tool may take long (a browser task): the call keeps going meanwhile. Checked with the real Live on 2026-09-24: while a
delegation waited 30 s for a function, the owner asked something else and Live answered it, then spoke the result."""
import asyncio
import hashlib
import itertools
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IDLE_SECONDS = 900
CALL_SECONDS = 600
_hosts = {}
_ids = itertools.count(1)


class Host:
    def __init__(self, user_id, room_id):
        self.user_id, self.room_id = user_id, room_id
        self.process = None
        self.waiting = {}
        self.used = time.monotonic()
        self.starting = None

    async def start(self):
        key = hashlib.sha1(f'{self.user_id}:{self.room_id}'.encode()).hexdigest()[:10]
        env = {**os.environ, 'DAN_USER_ID': self.user_id, 'DAN_SESSION_ID': self.room_id or '', 'DAN_TOOL_HOST': '1',
               # named like a job's browser: headless, its own profile (logins seeded from the owner's), kept between calls
               'DAN_BROWSER_ROOM': 'voice-job-call-' + key, 'DAN_BROWSER_HEADLESS': '1', 'DAN_BROWSER_OBSERVATION': 'dom',
               'DAN_WORK_DIR': f'D:/dan-workspace/jobs/call-{key}', 'DAN_CORE_PORT': '9000', 'PYTHONIOENCODING': 'utf-8'}
        os.makedirs(env['DAN_WORK_DIR'], exist_ok=True)
        creation = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0   # never a console window (owner's rule)
        self.process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'app.services.tool_host', cwd=str(ROOT), env=env,
                                                            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                            stderr=asyncio.subprocess.DEVNULL, creationflags=creation, limit=4 * 1024 * 1024)
        asyncio.create_task(self._read(self.process))

    async def _read(self, process):
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            try:
                reply = json.loads(line)
            except ValueError:
                continue
            future = self.waiting.pop(reply.get('id'), None)
            if future and not future.done():
                future.set_result(reply.get('text') or '')
        for future in self.waiting.values():
            if not future.done():
                future.set_result('操作は実行していません: ダンの道具の実行係が止まった')
        self.waiting.clear()

    def alive(self):
        return self.process is not None and self.process.returncode is None

    async def ask(self, op, **fields):
        if not self.alive():
            if not self.starting or self.starting.done():
                self.starting = asyncio.create_task(self.start())
            await self.starting
        self.used = time.monotonic()
        rid = next(_ids)
        future = asyncio.get_running_loop().create_future()
        self.waiting[rid] = future
        self.process.stdin.write((json.dumps({'id': rid, 'op': op, **fields}, ensure_ascii=False) + '\n').encode('utf-8'))
        await self.process.stdin.drain()
        try:
            return await asyncio.wait_for(future, CALL_SECONDS)
        finally:
            self.used = time.monotonic()

    def close(self):
        if self.alive():
            self.process.terminate()


def host(user_id, room_id):
    for key, h in list(_hosts.items()):
        if time.monotonic() - h.used > IDLE_SECONDS and not h.waiting:
            h.close(); _hosts.pop(key, None)
    key = (user_id, room_id)
    if key not in _hosts:
        _hosts[key] = Host(user_id, room_id)
    return _hosts[key]


def warm(user_id, room_id):
    """Start the owner's tool host in the background (at call start); a failure only means the first tool use starts it."""
    h = host(user_id, room_id)
    if not h.alive() and (not h.starting or h.starting.done()):
        h.starting = asyncio.create_task(h.start())
        h.starting.add_done_callback(lambda t: t.exception())   # retrieved: a failed warm-up is retried on first use
