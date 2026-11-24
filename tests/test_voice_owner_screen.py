"""The owner shows his screen in a call. Dan looks at it only when Jev says the request needs it (2026-11-25, the owner:
「書き足し続けるのは良くないと思う。…Jevが『今は画面を見た方が良い』と判断したらその時は見させる」). No call is placed: the
page is played by a task that answers the server's long poll the way call-owner-screen.tsx does."""
import asyncio
import base64
import io
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from PIL import Image

from app.api import voicelog_routes as routes
from app.services import prompt_store, voice_editor, voice_live, voice_lookup, voice_router
from app.services.voice_owner_screen import LAG, Screen
from app.services.voice_sideband import Dialogue, execute_call


def picture(color, size=(1280, 720)):
    stream = io.BytesIO()
    Image.new('RGB', size, color).save(stream, 'JPEG')
    return base64.b64encode(stream.getvalue()).decode()


class Clock:
    def __init__(self): self.now = 1_000_000.0
    def __call__(self): return self.now


def answer(choice, p):
    return {'type': 'choice', 'choice': choice, 'probabilities': {choice: p}, 'confidence': p}


class Judge:
    def __init__(self, answers): self.answers, self.asked = answers, []
    async def choose(self, state, questions):
        self.asked.append(questions)
        return {'available': True, 'answers': self.answers, 'elapsed_ms': 150}
    async def __aexit__(self, *a): return None


class Page:
    """The page of the call (call-owner-screen.tsx): it keeps pictures with its own times and answers a want with the
    pictures that were on the screen in that window (screen-frames.ts during)."""
    def __init__(self, screen, clock):
        self.screen, self.clock, self.frames, self.wants = screen, clock, [], []

    def show(self, color, surface='browser'):
        self.frames.append((self.clock(), picture(color), surface))

    async def serve(self):
        while True:
            want = await self.screen.next_want(timeout=5)
            if want is None: continue
            self.wants.append(want)
            now = self.clock()
            start, end = now - want['since_ago_ms'] / 1000, now - want['until_ago_ms'] / 1000
            on = [i for i, f in enumerate(self.frames) if f[0] <= start]
            chosen = [f for i, f in enumerate(self.frames) if (on and i == on[-1]) or start < f[0] <= end]
            self.screen.receive(want['id'], [{'ago_ms': round((now - at) * 1000), 'jpeg': jpeg, 'surface': s} for at, jpeg, s in chosen])


def setup(tmp_path, monkeypatch, said_at=()):
    monkeypatch.setenv('DAN_PROMPTS_DIR', str(tmp_path / 'prompts'))
    monkeypatch.setenv('DAN_VOICE_ROUTER', '1')
    monkeypatch.setenv('DAN_VOICE_PLAIN', '1')
    monkeypatch.setattr(voice_editor, 'call_editor', lambda room: None)
    monkeypatch.setattr(voice_router, 'enabled', lambda: True)
    monkeypatch.setattr('app.services.command_job_state.list_owned', lambda *args: [])
    clock = Clock()
    dialogue = Dialogue()
    screen = dialogue.owner_screen = Screen(dialogue, clock=clock)
    screen.folder = tmp_path / 'frames'
    monkeypatch.setitem(voice_live._sessions, 'session', {'user_id': 'u', 'room_id': 'r', 'owner_screen': screen})
    monkeypatch.setattr(routes, '_get_user', lambda _: SimpleNamespace(user_id='u'))
    return dialogue, screen, clock


def luna_router(monkeypatch, dialogue, judge):
    sent = []
    async def send(event): sent.append(event)
    model = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(
        output=[], usage=None, output_text='それは11月分の電気代の請求書です', id='answer'))))
    monkeypatch.setattr(voice_lookup, '_client', lambda model_name=None: model)
    r = voice_router.Router('session', 'u', 'r', dialogue, send, lambda *a, **k: None, {},
                            backend={'model': 'gpt-6-luna', 'instructions': 'i', 'tools': []})
    r.judge = judge
    r.targets = {}
    monkeypatch.setattr(r, 'call_context', lambda _=(): '')
    dialogue.heard_at = 0.0
    return r, sent, model


def images(model):
    parts = model.responses.create.await_args.kwargs['input'][0]['content']
    return parts, [p['image_url'].split(',')[1] for p in parts if isinstance(p, dict) and p.get('type') == 'input_image']


async def say(dialogue, clock, *pieces, gap=1.0):
    for piece in pieces:
        clock.now += gap
        dialogue.add('user', piece)


@pytest.mark.asyncio
async def test_a_request_about_the_screen_gets_the_pictures_from_while_he_said_it(tmp_path, monkeypatch):
    """① and ③: 「これ何？」 is looked at; the tab he opened after he finished speaking is not among the pictures."""
    dialogue, screen, clock = setup(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as denied:
        await routes.start_owner_screen('other-room', routes.ScreenSession(session_id='session', surface='browser'), None)
    assert denied.value.status_code == 403
    await routes.start_owner_screen('r', routes.ScreenSession(session_id='session', surface='browser'), None)
    page = Page(screen, clock)
    serving = asyncio.create_task(page.serve())
    page.show('white')                       # a page he looked at before
    clock.now += 20
    page.show('green')                       # the invoice, on the screen while he speaks
    await say(dialogue, clock, 'ねえ', 'これ', '何の請求書？')
    clock.now += 1.5
    page.show('red')                         # he moved to another tab right after he finished
    r, sent, model = luna_router(monkeypatch, dialogue, Judge({'route': answer('other', .9), 'look': answer('look', .9)}))
    await r.answer('d1', time.monotonic())
    serving.cancel()
    parts, given = images(model)
    assert given == [page.frames[1][1]]      # the invoice only: not the earlier page, not the tab opened after
    assert any('何の請求書' in p.get('text', '') and 'タブ' in p.get('text', '') for p in parts if p.get('type') == 'input_text')
    assert prompt_store.text('call/screen-backend') in [p.get('text') for p in parts]
    # ④ the speech model hears the answer only: no picture, nothing about the screen
    spoken = json.dumps(sent, ensure_ascii=False)
    assert 'image' not in spoken and '共有' not in spoken and '画面' not in spoken
    assert sent[-1]['content'] == 'それは11月分の電気代の請求書です'


@pytest.mark.asyncio
async def test_a_request_that_needs_no_screen_takes_no_picture(tmp_path, monkeypatch):
    """②: 「明日の天気は？」 with the screen shared: the page is never asked, nothing is sent from it."""
    dialogue, screen, clock = setup(tmp_path, monkeypatch)
    await routes.start_owner_screen('r', routes.ScreenSession(session_id='session', surface='monitor'), None)
    page = Page(screen, clock)
    serving = asyncio.create_task(page.serve())
    page.show('green', 'monitor')
    await say(dialogue, clock, '今日の天気って', 'どう？')
    judge = Judge({'route': answer('other', .9), 'look': answer('no', .9)})
    r, sent, model = luna_router(monkeypatch, dialogue, judge)
    await r.answer('d2', time.monotonic())
    serving.cancel()
    assert 'look' in judge.asked[0]           # Jev was asked whether to look
    assert page.wants == [] and images(model)[1] == []
    assert not r.dialogue.screen_seen


@pytest.mark.asyncio
async def test_he_asks_to_look_and_dan_always_looks(tmp_path, monkeypatch):
    dialogue, screen, clock = setup(tmp_path, monkeypatch)
    await routes.start_owner_screen('r', routes.ScreenSession(session_id='session', surface='window'), None)
    page = Page(screen, clock)
    serving = asyncio.create_task(page.serve())
    page.show('blue', 'window')
    await say(dialogue, clock, 'ちょっと画面見て')
    r, sent, model = luna_router(monkeypatch, dialogue, Judge({'route': answer('lookup', .9), 'look': answer('no', .8)}))
    await r.answer('d3', time.monotonic())
    serving.cancel()
    parts, given = images(model)              # the lookup reads no pictures: the model that sees them answers
    assert given == [page.frames[0][1]]
    assert any('マウスの矢印が本人の指している所' in p.get('text', '') for p in parts if p.get('type') == 'input_text')


@pytest.mark.asyncio
async def test_when_jev_does_not_answer_the_backend_gets_the_shared_screen(tmp_path, monkeypatch):
    """Jev out of reach (its budget, the network): the earlier backend answers every request; with a shared screen it gets
    the pictures and is told not to talk about them unasked (call/screen-backend)."""
    dialogue, screen, clock = setup(tmp_path, monkeypatch)
    await routes.start_owner_screen('r', routes.ScreenSession(session_id='session', surface='browser'), None)
    page = Page(screen, clock)
    serving = asyncio.create_task(page.serve())
    page.show('green')
    await say(dialogue, clock, 'これって', '安い？')
    class Down(Judge):
        async def choose(self, state, questions): return {'available': False, 'reason': 'unavailable', 'elapsed_ms': 1}
    r, sent, model = luna_router(monkeypatch, dialogue, Down({}))
    await r.answer('d6', time.monotonic())
    serving.cancel()
    assert images(model)[1] == [page.frames[0][1]] and dialogue.looking is None


@pytest.mark.asyncio
async def test_without_a_shared_screen_dan_says_he_cannot_see_it(tmp_path, monkeypatch):
    dialogue, screen, clock = setup(tmp_path, monkeypatch)
    await say(dialogue, clock, 'これ何？')
    r, sent, model = luna_router(monkeypatch, dialogue, Judge({'route': answer('other', .9), 'look': answer('look', .9)}))
    await r.answer('d4', time.monotonic())
    parts, given = images(model)
    assert given == [] and prompt_store.text('call/screen-unseen') in [p.get('text') for p in parts]


@pytest.mark.asyncio
async def test_work_started_from_the_call_gets_the_pictures_as_files(tmp_path, monkeypatch):
    dialogue, screen, clock = setup(tmp_path, monkeypatch)
    await routes.start_owner_screen('r', routes.ScreenSession(session_id='session', surface='browser'), None)
    page = Page(screen, clock)
    serving = asyncio.create_task(page.serve())
    page.show('green')
    await say(dialogue, clock, 'このページの', '見出しを直して')
    started = []
    async def execute(params, room_id, user_id, voice_handoff=False, internal_check=False):
        started.append(params)
        return {'accepted': True, 'receipt': {'id': 'job-1'}}
    monkeypatch.setattr('app.services.command_center.execute', execute)
    monkeypatch.setattr('app.services.parallel_job_runner.room_model', lambda room: 'opus')
    r, sent, model = luna_router(monkeypatch, dialogue, Judge({'route': answer('make', .9), 'look': answer('look', .9)}))
    await r.answer('d5', time.monotonic())
    serving.cancel()
    task = started[0]['task']
    files = list(screen.folder.glob('*.jpg'))
    assert len(files) == 1 and str(files[0]) in task and files[0].read_bytes() == base64.b64decode(page.frames[0][1])
    assert 'このページの見出しを直して' in task
    # luna's own start_work carries the same pictures
    from app.services import command_center
    start = AsyncMock(return_value={'accepted': True, 'receipt': {'id': 'job-2'}})
    monkeypatch.setattr(command_center, 'execute', start)
    await execute_call({'name': 'start_work', 'arguments': '{"task":"これを直して","kind":"make"}', 'call_id': 'c'},
                       'u', 'r', dialogue, lambda *a, **k: None, 'd')
    assert str(files[0]) in start.await_args.args[0]['task']


@pytest.mark.asyncio
async def test_the_window_is_when_he_said_it_and_a_stopped_share_gives_nothing(tmp_path, monkeypatch):
    dialogue, screen, clock = setup(tmp_path, monkeypatch)
    screen.start('browser')
    await say(dialogue, clock, '前の話', gap=10)
    await say(dialogue, clock, 'これ', 'どう思う？', gap=2)
    clock.now += 3                                    # Jev and the router take their time
    began, ended = screen.window('これどう思う？')
    assert began == pytest.approx(clock.now - 3 - 2 - LAG) and ended == pytest.approx(clock.now - 3 - LAG)
    assert screen.stop() and not screen.sharing()
    assert await screen.look('これどう思う？') == []
    with pytest.raises(HTTPException):
        await routes.receive_owner_screen('r', routes.ScreenPictures(session_id='session', want_id='x', frames=[
            routes.ScreenPicture(ago_ms=0, jpeg=picture('red', (4000, 100)))]), None)
    # a want nobody waits for is not accepted; an oversized picture is refused
    assert not screen.receive('nobody', [])


def test_the_speech_model_is_told_nothing_about_the_screen():
    import inspect
    from app.services import voice_owner_screen
    source = inspect.getsource(voice_owner_screen)
    assert 'instructions.append' not in source and 'commentary.append' not in source and 'thinking.append' not in source
    assert not (prompt_store.SEED / 'call' / 'screen.md').exists()
