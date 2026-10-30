from types import SimpleNamespace
import pytest
from app.services import voice_external_screen as E

class Stage:
    version = 1
    image = 'old'
    def _apply(self, caption, image):
        self.version += 1
        self.image = image
        self.caption = caption

class Host:
    def __init__(self, replies): self.replies, self.calls = iter(replies), []
    async def ask(self, op, **kw):
        self.calls.append(kw)
        reply = next(self.replies)
        if isinstance(reply, Exception): raise reply
        return reply

@pytest.mark.asyncio
@pytest.mark.parametrize('tool', ['browser', 'browser_plan', 'browser_flow', 'phone'])
async def test_first_operation_shows_actual_screen_without_opt_in(tool):
    stage = Stage()
    host = Host([{'text': 'clicked', 'stage_image': '/api/v1/files/current.png'}])
    result = await E.execute(host, stage, tool, {'action': 'click'})
    assert result == {'result': 'clicked', 'screen': {'shown': True}}
    assert stage.image.endswith('current.png') and len(host.calls) == 1
    assert stage._external_source == E.SOURCES[tool]

@pytest.mark.asyncio
async def test_phone_fallback_uses_same_device_and_does_not_repeat_action():
    host = Host([{'text': 'unknown'}, {'stage_image': '/api/v1/files/after.png'}])
    stage = Stage()
    await E.execute(host, stage, 'phone', {'action': 'tap', 'serial': 'test-device'})
    assert [c['arguments']['action'] for c in host.calls] == ['tap', 'screenshot']
    assert host.calls[1]['arguments']['serial'] == 'test-device'

@pytest.mark.asyncio
async def test_missing_picture_does_not_leave_stale_evidence_or_hide_result():
    stage = Stage()
    result = await E.execute(Host([{'text': 'dispatch uncertain'}, RuntimeError()]), stage, 'browser', {'action': 'click'})
    assert result['result'] == 'dispatch uncertain'
    assert not result['screen']['shown'] and stage.image == ''

@pytest.mark.asyncio
async def test_slow_operation_cannot_overwrite_new_scene():
    stage = Stage()
    class Slow:
        async def ask(self, *a, **k):
            stage._apply('new view', image='/api/v1/files/new.png')
            return {'stage_image': '/api/v1/files/old.png'}
    result = await E.execute(Slow(), stage, 'browser', {'action': 'click'})
    assert not result['screen']['shown'] and stage.image.endswith('new.png')

@pytest.mark.asyncio
@pytest.mark.parametrize('tool,action', [('browser','close'),('browser','session_status'),('phone','devices'),('web_search','search')])
async def test_non_screen_calls_preserve_view(tool, action):
    stage = Stage()
    host = Host([{'text': 'ok'}])
    assert await E.execute(host, stage, tool, {'action': action}) == {'result':'ok'}
    assert stage.image == 'old' and len(host.calls) == 1
