"""Exercise the room/session boundary, picture order and the actual voice-to-work handoff without placing a call."""
import base64
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from PIL import Image

from app.api import voicelog_routes as routes
from app.services import prompt_store, voice_editor, voice_live, voice_lookup, voice_router
from app.services.voice_sideband import Dialogue, execute_call
from app.services.voice_sketch import Sketch


def picture(color):
    stream = io.BytesIO()
    Image.new('RGB', (64, 40), color).save(stream, 'JPEG')
    return base64.b64encode(stream.getvalue()).decode()


@pytest.mark.asyncio
async def test_shared_drawings_reach_visual_reasoning_and_work(tmp_path, monkeypatch):
    monkeypatch.setenv('DAN_PROMPTS_DIR', str(tmp_path / 'prompts'))
    monkeypatch.setenv('DAN_VOICE_ROUTER', '1')
    monkeypatch.setattr(voice_editor, 'call_editor', lambda room: None)
    dialogue = Dialogue()
    board = dialogue.sketch = Sketch(dialogue, AsyncMock())
    board.folder = tmp_path / 'frames'
    state = {'user_id': 'u', 'room_id': 'r', 'sketch': board}
    monkeypatch.setitem(voice_live._sessions, 'session', state)
    monkeypatch.setattr(routes, '_get_user', lambda _: SimpleNamespace(user_id='u'))
    async def share(room, seq, image):
        return await routes.receive_sketch(room, routes.SketchFrame(session_id='session', number=seq, jpeg=image), None)
    red, blue = picture('red'), picture('blue')
    with pytest.raises(HTTPException) as denied:
        await share('different-room', 1, red)
    assert denied.value.status_code == 403 and not board.frames
    dialogue.add('user', 'ここは赤')
    assert (await share('r', 1, red))['accepted']
    dialogue.add('user', '、次の四角は青')
    assert (await share('r', 2, blue))['accepted']
    assert not (await share('r', 1, red))['accepted']
    board.send.assert_awaited_once()
    assert board.send.await_args.args[0]['content'] == prompt_store.text('call/sketch')

    model = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(
        output=[], usage=None, output_text='確認しました', id='answer'))))
    monkeypatch.setattr(voice_lookup, '_client', lambda model_name: model)
    router = voice_router.Router('session', 'u', 'r', dialogue, AsyncMock(), lambda *a, **k: None, {},
                                backend={'model': 'gpt-6-luna'}, observe_only=True)
    monkeypatch.setattr(router, 'call_context', lambda _: '')
    assert (await router.route())[0] == 'other'
    await router._luna_loop('d')
    parts = model.responses.create.await_args.kwargs['input'][0]['content']
    assert [p['image_url'].split(',')[1] for p in parts if p['type'] == 'input_image'] == [red, blue]
    assert 'ここは赤' in parts[1]['text'] and '四角は青' in parts[3]['text']

    from app.services import command_center
    start = AsyncMock(return_value={'accepted': True, 'receipt': {'id': 'new-job'}})
    monkeypatch.setattr(command_center, 'execute', start)
    monkeypatch.setattr('app.services.command_job_state.list_owned', lambda *args: [])
    await execute_call({'name':'start_work', 'arguments':'{"task":"この順に並べる","kind":"make"}', 'call_id':'c'},
                       'u', 'r', dialogue, lambda *a, **k:None, 'd')
    task = start.await_args.args[0]['task']
    for seq, jpeg in [(1, red), (2, blue)]:
        file = board.folder / f'{seq}.jpg'
        assert str(file) in task and file.read_bytes() == base64.b64decode(jpeg)
