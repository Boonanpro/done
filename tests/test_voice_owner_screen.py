"""The owner shows his screen in a call and asks 「これ何？」: the picture reaches the model that decides, and work started
from the call gets it as a file. No call is placed."""
import base64
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from PIL import Image

from app.api import voicelog_routes as routes
from app.services import prompt_store, voice_editor, voice_live, voice_lookup, voice_router
from app.services.voice_owner_screen import Screen
from app.services.voice_sideband import Dialogue, execute_call


def picture(color, size=(1280, 720)):
    stream = io.BytesIO()
    Image.new('RGB', size, color).save(stream, 'JPEG')
    return base64.b64encode(stream.getvalue()).decode()


def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('DAN_PROMPTS_DIR', str(tmp_path / 'prompts'))
    monkeypatch.setenv('DAN_VOICE_ROUTER', '1')
    monkeypatch.setattr(voice_editor, 'call_editor', lambda room: None)
    monkeypatch.setattr(voice_router, 'enabled', lambda: True)
    dialogue = Dialogue()
    screen = dialogue.owner_screen = Screen(dialogue, AsyncMock())
    screen.folder = tmp_path / 'frames'
    monkeypatch.setitem(voice_live._sessions, 'session', {'user_id': 'u', 'room_id': 'r', 'owner_screen': screen})
    monkeypatch.setattr(routes, '_get_user', lambda _: SimpleNamespace(user_id='u'))
    return dialogue, screen


async def share(room, seq, image, surface='monitor'):
    return await routes.receive_owner_screen(room, routes.ScreenFrame(session_id='session', number=seq, jpeg=image, surface=surface), None)


@pytest.mark.asyncio
async def test_this_on_a_shared_screen_reaches_the_model_that_sees_and_the_work(tmp_path, monkeypatch):
    dialogue, screen = setup(tmp_path, monkeypatch)
    old, now = picture('white'), picture('green')
    with pytest.raises(HTTPException) as denied:
        await share('other-room', 1, old)
    assert denied.value.status_code == 403 and not screen.frames
    assert (await share('r', 1, old))['accepted']
    assert (await share('r', 2, now))['accepted']
    assert not (await share('r', 1, old))['accepted']          # a late older picture does not replace the newer
    screen.send.assert_awaited_once()
    assert screen.send.await_args.args[0]['content'] == prompt_store.text('call/screen')

    router = voice_router.Router('session', 'u', 'r', dialogue, AsyncMock(), lambda *a, **k: None, {},
                                 backend={'model': 'gpt-6-luna'}, observe_only=True)
    dialogue.add('user', '今日って何曜日だっけ')
    assert not screen.points(router.request_words())             # not about the screen: the usual fast routes
    dialogue.add('user', 'これ何？')
    assert (await router.route())[0] == 'other'

    model = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(
        output=[], usage=None, output_text='緑の画面です', id='answer'))))
    monkeypatch.setattr(voice_lookup, '_client', lambda model_name: model)
    monkeypatch.setattr(router, 'call_context', lambda _: '')
    await router._luna_loop('d')
    parts = model.responses.create.await_args.kwargs['input'][0]['content']
    images = [p['image_url'].split(',')[1] for p in parts if p['type'] == 'input_image']
    assert images == [now]                                        # only the newest picture
    assert any('マウスの矢印が本人の指している所' in p.get('text', '') for p in parts)
    assert 'これ何' in parts[0]['text']                            # his words are in the call's transcript

    from app.services import command_center
    start = AsyncMock(return_value={'accepted': True, 'receipt': {'id': 'new-job'}})
    monkeypatch.setattr(command_center, 'execute', start)
    monkeypatch.setattr('app.services.command_job_state.list_owned', lambda *args: [])
    await execute_call({'name': 'start_work', 'arguments': '{"task":"これを直して","kind":"make"}', 'call_id': 'c'},
                       'u', 'r', dialogue, lambda *a, **k: None, 'd')
    task = start.await_args.args[0]['task']
    file = screen.folder / '2.jpg'
    assert str(file) in task and file.read_bytes() == base64.b64decode(now)


@pytest.mark.asyncio
async def test_after_stopping_the_share_nothing_old_is_shown(tmp_path, monkeypatch):
    dialogue, screen = setup(tmp_path, monkeypatch)
    assert (await share('r', 1, picture('red'), 'browser'))['accepted']
    assert 'タブ' in screen.parts()[0]['text'] and '映っていない' in screen.parts()[0]['text']
    stopped = await routes.stop_owner_screen('r', routes.ScreenStop(session_id='session'), None)
    assert stopped['stopped'] and not screen.sharing() and screen.parts() == []
    assert screen.send.await_args.args[0]['content'] == prompt_store.text('call/screen-ended')
    dialogue.add('user', 'これ何？')
    assert not screen.points('これ何？')
    with pytest.raises(HTTPException):
        await share('r', 2, picture('red', (4000, 100)))         # an oversized picture is refused
