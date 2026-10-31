import time
from types import SimpleNamespace
import pytest
from app.services import voice_viewport as V, voice_stage as S

@pytest.fixture
def display(tmp_path, monkeypatch):
    monkeypatch.setattr(V, 'ROOT', tmp_path)
    state = {'active': True, 'session_id': 'call-a'}
    monkeypatch.setattr(S, 'read_state', lambda room: state)
    return state


def body(**kw):
    return dict(session_id='call-a', client_id='phone', width=390, height=700, **kw)


def test_stale_call_and_second_device_cannot_resize_current_display(display):
    assert V.accept('room',display,body())
    assert V.current('room') == {'width':390,'height':700}
    other = body(); other.update(client_id='pc',width=1440)
    assert not V.accept('room',display,other)
    other.update(session_id='older-call')
    assert not V.accept('room',display,other)
    assert V.current('other-room') is None
    display['session_id']='new-call'
    assert V.current('room') is None
    display.update(active=False)
    assert not V.accept('room',display,body())


def test_expired_display_does_not_resize_unattended_browser(display):
    assert V.accept('room',display,body())
    data=V.read('room');data['received_at']=time.time()-13
    import json
    V.path('room').write_text(json.dumps(data))
    assert V.current('room') is None
    other=body();other['client_id']='pc'
    assert V.accept('room',display,other)
    bad=body();bad['width']=0
    assert not V.accept('room',display,bad)


@pytest.mark.asyncio
async def test_phone_viewport_reflows_real_browser_and_retains_page_state(display, tmp_path, monkeypatch):
    from playwright.async_api import async_playwright
    from app.services import voice_screen_stream as stream
    monkeypatch.setattr(stream,'directory',lambda room:tmp_path/'frames'/room)
    assert V.accept('room',display,body())
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page(viewport={'width':1440,'height':900})
        # An unfamiliar page: no artifact name, selectors, or site-specific zoom.
        await page.set_content('<meta name="viewport" content="width=device-width"><style>body{margin:0;font:18px sans-serif}.menu{width:260px;float:left}.article{margin-left:280px} @media(max-width:600px){.menu{display:none}.article{margin:16px}}</style><nav class="menu">Navigation</nav><main class="article"><h1>部品の接続条件</h1><p>表示部品と接続基板の仕様を確認します。</p><input aria-label="検討メモ" value="未確定"></main>')
        await page.locator('input').fill('見積もり待ち')
        monkeypatch.setenv('DAN_TOOL_HOST','1');monkeypatch.setenv('DAN_SESSION_ID','room')
        execution={}
        await stream.follow_browser(execution,page)
        assert page.viewport_size=={'width':1440,'height':900}  # no resize in an action
        await stream.follow_browser(execution,page,fit_viewport=True)
        live=execution['voice_stream']
        try:
            assert page.viewport_size=={'width':390,'height':700}
            assert not await page.locator('nav').is_visible()
            assert await page.locator('input').input_value()=='見積もり待ち'
            for _ in range(40):
                if live.data:break
                import asyncio
                await asyncio.sleep(.05)
            assert live.data
            from PIL import Image
            import io
            assert Image.open(io.BytesIO(live.data)).size==(390,700)
        finally:
            await live.close();await browser.close()


@pytest.mark.asyncio
async def test_viewport_route_checks_room_owner(display,monkeypatch):
    from app.api import voicelog_routes as R
    from fastapi import HTTPException
    monkeypatch.setattr(R,'_get_user',lambda r:SimpleNamespace(user_id='u'))
    class Rooms:
        async def get_room(self,*a):return None
    monkeypatch.setattr(R,'ChatService',Rooms)
    with pytest.raises(HTTPException) as error:
        await R.call_viewport('room',None,R.StageViewport(**body()))
    assert error.value.status_code==403
    assert V.current('room') is None
