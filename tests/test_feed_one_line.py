"""A tab keeps exactly one feed line, and the room's screens hear when Dan's work starts and ends (2026-10-13).

Before: after each restart of the core a tab that was looked at during the drop kept one more unclosed line, then twice as
many (1 -> 2 -> 4 -> 7 -> 14). Lines share the browser's limit of simultaneous requests to one host with everything else,
so sending a message and reloading the page stopped going out, and "Dan is working", lit by the screen at the moment of
sending, was never corrected."""
import asyncio
import shutil
import subprocess
import types
from pathlib import Path

import pytest

from app.agent import cli_runner
from app.services import room_feed, run_service

ROOT = Path(__file__).resolve().parents[1]

SCENARIO = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const ts = require(process.argv[2]);
const box = { exports: {} };
let now = 0, timers = [];
const clock = {
  setTimeout: (f, ms) => { const t = { f, at: now + ms }; timers.push(t); return t; },
  clearTimeout: (t) => { timers = timers.filter((x) => x !== t); },
};
const pass = (ms) => { now += ms; for (;;) { const due = timers.filter((t) => t.at <= now); if (!due.length) break; timers = timers.filter((t) => !due.includes(t)); due.forEach((t) => t.f()); } };
vm.runInNewContext(ts.transpileModule(fs.readFileSync(process.argv[3], 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, { exports: box.exports, ...clock });
const lines = [];   // every line ever opened; like a browser's EventSource, one that errored and was not closed stays alive
const open = (on) => { const l = { on, closed: false, close() { this.closed = true; } }; lines.push(l); return l; };
const live = () => lines.filter((l) => !l.closed);
let drops = 0;
const feed = box.exports.oneLine(open, () => { drops += 1; });
const restart = (lookedAt) => {             // the core stops: every unclosed line errors; the tab may be looked at before it is back
  live().forEach((l) => l.on.dropped());
  if (lookedAt) feed.connectIfClosed();
  pass(40000);                              // the retries run
  live().forEach((l) => l.on.up());
};
feed.connect();
assert.equal(live().length, 1);
for (let n = 0; n < 6; n++) { restart(n % 2 === 0); assert.equal(live().length, 1, 'one line after restart ' + (n + 1)); }
assert.equal(drops, 6);
assert.equal(timers.length, 0, 'no retry is left waiting while the line is up');

feed.connect(); feed.connect();             // asked twice (back from a restart, then looked at): still one
assert.equal(live().length, 1);

const before = lines.length;                // a line that keeps failing is retried later and later, one at a time
live()[0].on.dropped(); pass(999); assert.equal(lines.length, before);
pass(1); assert.equal(lines.length, before + 1);
live()[0].on.dropped(); pass(1999); assert.equal(lines.length, before + 1);
pass(1); assert.equal(lines.length, before + 2);

lines[0].on.dropped();                      // a line closed long ago reports an error late: nothing happens
assert.equal(live().length, 1);

feed.close(); assert.equal(live().length, 0); pass(120000); assert.equal(live().length, 0);   // in the background: closed, no retry
feed.connectIfClosed(); assert.equal(live().length, 1);
feed.stop(); feed.connect(); pass(120000); assert.equal(live().length, 0);
console.log('ok');
"""


@pytest.mark.parametrize('module', ['frontend/src/lib/one-line.ts', 'mobile/one-line.ts'])
def test_restarts_and_looking_at_the_tab_leave_exactly_one_line(module, tmp_path):
    typescript = ROOT / 'frontend' / 'node_modules' / 'typescript'
    if not shutil.which('node') or not typescript.exists():
        pytest.skip('node and the frontend packages are needed to run the screen code')
    script = tmp_path / 'scenario.cjs'
    script.write_text(SCENARIO, encoding='utf-8')
    done = subprocess.run(['node', str(script), str(typescript), str(ROOT / module)], capture_output=True, text=True, encoding='utf-8')
    assert done.returncode == 0 and done.stdout.strip() == 'ok', done.stderr[-2000:]


def test_the_screen_and_the_app_hold_the_same_one_line_rules():
    def body(path):
        return (ROOT / path).read_text(encoding='utf-8').split('export type Line', 1)[1]
    assert body('frontend/src/lib/one-line.ts') == body('mobile/one-line.ts')


RUN = {'id': 'run', 'room_id': 'room', 'project_id': 'project', 'state': 'running', 'metadata': {}}


def heard(write, monkeypatch, in_core=True):
    """What a screen of the room's member receives while `write` runs."""
    async def scenario():
        queue = asyncio.Queue()
        room_feed._subs['member'][queue] = asyncio.get_running_loop()
        monkeypatch.setattr(room_feed, '_IN_CORE', in_core)
        monkeypatch.setattr(room_feed, '_room_members', lambda room: ['member'] if room == 'room' else [])
        try:
            result = write()
            if asyncio.iscoroutine(result):
                await result
            await asyncio.sleep(0.05)
            events = []
            while not queue.empty():
                events.append({k: v for k, v in queue.get_nowait().items() if k != 'at'})
            return events
        finally:
            room_feed._subs.pop('member', None)
    return asyncio.run(scenario())


def test_the_rooms_screens_hear_a_run_start_and_end(monkeypatch):
    assert heard(lambda: room_feed.publish_run(RUN), monkeypatch) == [
        {'type': 'run', 'project_id': 'project', 'room_id': 'room', 'running': True}]
    for state in ('completed', 'failed', 'paused', 'awaiting_approval', 'superseded'):
        assert heard(lambda: room_feed.publish_run(dict(RUN, state=state)), monkeypatch)[0]['running'] is False


def test_work_in_the_background_is_not_the_chat_working(monkeypatch):
    assert heard(lambda: room_feed.publish_run(dict(RUN, metadata={'started_by': 'command_center'})), monkeypatch) == []


def test_a_run_written_outside_the_core_is_handed_to_the_core(monkeypatch):
    posted = []
    monkeypatch.setattr(room_feed, '_post_to_core', lambda path, payload: posted.append((path, payload)) or 1)
    assert heard(lambda: room_feed.publish_run(RUN), monkeypatch, in_core=False) == []
    assert posted == [('runs', {'room_id': 'room', 'project_id': 'project', 'state': 'running', 'metadata': {}})]


class Table:
    def __init__(self, db):
        self.db, self.row = db, None

    def insert(self, row):
        self.row = dict(RUN, **row)
        return self

    def update(self, changes):
        self.row = dict(RUN, **changes)
        return self

    def __getattr__(self, _):
        return lambda *a, **k: self

    def execute(self):
        return types.SimpleNamespace(data=[self.row] if self.row else [])


class Database:
    def table(self, name):
        return Table(self)


def test_every_writer_of_a_runs_state_announces_it(monkeypatch):
    db = Database()
    import app.services.supabase_client as client
    monkeypatch.setattr(client, 'get_supabase_client', lambda: types.SimpleNamespace(client=db))
    service = run_service.RunService.__new__(run_service.RunService)
    service.supabase = db
    running = [{'type': 'run', 'project_id': 'project', 'room_id': 'room', 'running': True}]
    ended = [dict(running[0], running=False)]
    assert heard(lambda: service.create_run('project', 'room'), monkeypatch) == running
    assert heard(lambda: service.update_run('run', state='completed'), monkeypatch) == ended
    assert heard(lambda: service.update_run('run', claude_session_id='s'), monkeypatch) == []     # not a change of state
    assert heard(lambda: cli_runner._update_run_sync('run', state='failed'), monkeypatch) == ended
    assert heard(lambda: cli_runner._update_run_sync('run', claude_session_id='s'), monkeypatch) == []


def test_a_failed_announcement_never_breaks_the_writer(monkeypatch):
    def broken(run):
        raise RuntimeError('no route to the core')
    monkeypatch.setattr(room_feed, 'publish_run', broken)
    run_service.announce(RUN)


def test_the_internal_entry_hands_a_run_to_the_rooms_screens(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import chat_routes
    app = FastAPI()
    app.include_router(chat_routes.router, prefix='/api/v1')
    seen = []
    monkeypatch.setattr(room_feed, 'publish_run', lambda run: seen.append(run) or 2)
    assert TestClient(app, client=('127.0.0.1', 50000)).post('/api/v1/chat/internal/runs', json=RUN).json() == {'ok': True, 'delivered': 2}
    assert TestClient(app, client=('203.0.113.7', 50000)).post('/api/v1/chat/internal/runs', json=RUN).status_code == 403
    assert seen == [RUN]
