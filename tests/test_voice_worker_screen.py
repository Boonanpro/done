from types import SimpleNamespace
import pytest
from app.services.voice_worker_screen import Follower, observe
from app.services import voice_external_screen as E, voice_tools, command_job_state

class Stage:
    user_id = 'u'
    room_id = 'r'
    version = 1
    image = ''
    frame = ''
    def _apply(self, caption, image):
        self.image = image
        self.version += 1

def job(**kw):
    return dict(id='j', user_id='u', origin_room_id='r', state='running', browser_room='worker',
                screen=dict(at='2026-10-31T07:01:00', url='/api/v1/files/actual.png', browser_room='worker'), **kw)

def test_only_current_room_owner_fresh_screen_and_newer_scene_wins():
    stage=Stage(); f=Follower(stage,'u','r','2026-10-31T07:00:00')
    for patch in ({'user_id':'other'}, {'origin_room_id':'other'}, {'state':'cancelled'}, {'browser_room':'other'}):
        j=job();j.update(patch);f.update([j]);assert stage.image == ''
    # A rejected snapshot must not consume the next valid snapshot.
    f=Follower(stage,'u','r','2026-10-31T07:00:00'); f.update([job()])
    assert stage.image.endswith('actual.png') and stage._external_browser_room=='worker'
    version=stage.version;f.update([job()]);assert stage.version==version
    stage._apply('owner scene',image='/api/v1/files/new.png')
    j=job();j['screen']['at']='2026-10-31T07:02:00';f.update([j])
    assert stage.image.endswith('new.png')

def test_old_observation_never_displays_in_new_call():
    stage=Stage();Follower(stage,'u','r','2026-10-31T08:00:00').update([job()])
    assert stage.image==''

@pytest.mark.asyncio
async def test_scroll_routes_to_displayed_worker_and_busy_worker_is_not_interrupted(monkeypatch):
    stage=Stage();Follower(stage,'u','r','2026-10-31T07:00:00').update([job()])
    calls=[]
    class Host:
        browser_room='worker'
        async def ask(self, *a, **kw):
            calls.append(kw);return {'text':'ok','stage_image':'/api/v1/files/actual.png'}
    host=Host()
    def owned(*args):
        assert args==('j','u','r');return {'browser_room':'worker','current_tool':{'name':'browser'}}
    monkeypatch.setattr(command_job_state,'owned',owned)
    assert not (await E.scroll(None,stage,'down'))['ok'];assert not calls
    monkeypatch.setattr(command_job_state,'owned',lambda *a:{'browser_room':'worker'})
    def gethost(u,r,browser_room=None):
        assert (u,r,browser_room)==('u','r','worker');return host
    monkeypatch.setattr(voice_tools,'host',gethost)
    assert (await E.scroll(None,stage,'down'))['screen']['shown']
    assert len(calls)==1 and calls[0]['arguments']['action']=='scroll'
    assert stage._external_job_id=='j'

@pytest.mark.asyncio
async def test_observe_uses_worker_executor_and_never_retries_operation(monkeypatch):
    from app.tools import browser
    calls=[];row={'state':'running'}
    monkeypatch.setenv('DAN_BROWSER_ROOM','worker')
    monkeypatch.setattr(browser,'_send_executor_command',lambda cmd: calls.append(cmd) or '/api/v1/files/actual.png')
    monkeypatch.setattr(command_job_state,'change',lambda id,fn:fn(row))
    await observe('j','browser',{'action':'click'})
    assert calls==['voice_stream_url'] and row['screen']['browser_room']=='worker'
    await observe('j','browser',{'action':'session_status'})
    assert len(calls)==1

def test_initial_caption_does_not_block_first_worker_screen():
    stage=Stage();f=Follower(stage,'u','r','2026-10-31T07:00:00')
    stage.version+=1
    f.update([job()])
    assert stage.image.endswith('actual.png')

@pytest.mark.asyncio
async def test_compose_delivers_touchable_saved_draft_and_keeps_it_while_worker_browses(monkeypatch, tmp_path):
    from app.services import voice_stage as V
    from app.services.outbound_message_service import OutboundMessageService
    monkeypatch.setattr(V, 'ROOT', tmp_path)
    row = dict(id='p', user_id='u', source_room_id='r', status='pending', content='投稿する前に直す本文',
               action_data=dict(channel='x_post', to='example', attachments=[dict(url='/api/v1/files/demo.mp4', type='video/mp4')]))
    j = job()
    monkeypatch.setattr(command_job_state, 'read', lambda _: j)
    monkeypatch.setattr(command_job_state, 'change', lambda _, fn: fn(j))
    monkeypatch.setattr(OutboundMessageService, '__init__', lambda self: None)
    monkeypatch.setattr(OutboundMessageService, 'get', lambda self, pid, uid: row if (pid, uid) == ('p', 'u') else None)
    await observe('j', 'compose_message', {'action':'propose'}, {'success':True, 'proposal_id':'p'})
    stage = V.Stage('r', 'no-call', None, lambda *a, **kw: None, user_id='u')
    f = Follower(stage, 'u', 'r', '2026-10-31T07:00:00')
    f.update([j])
    assert stage.card['proposal_id'] == 'p' and stage.card['attachments'][0]['url'].endswith('demo.mp4')
    assert stage.image == ''
    j['screen']['at'] = '2099-01-01T00:00:00'
    f.update([j])
    assert stage.card['body'] == row['content'] and stage.image == ''
    # Another owner, room, cancelled job, or previous call cannot show its card.
    for patch in ({'user_id':'other'}, {'origin_room_id':'other'}, {'state':'cancelled'}):
        rejected = {**j, **patch}
        fresh = V.Stage('r', 'no-call', None, lambda *a, **kw: None, user_id='u')
        Follower(fresh, 'u', 'r', '2026-10-31T07:00:00').update([rejected])
        assert not fresh.card
    fresh = V.Stage('r', 'no-call', None, lambda *a, **kw: None, user_id='u')
    Follower(fresh, 'u', 'r', '2099-01-02T00:00:00').update([j])
    assert not fresh.card

@pytest.mark.asyncio
async def test_failed_compose_or_other_rooms_draft_never_becomes_a_preview(monkeypatch):
    from app.services.outbound_message_service import OutboundMessageService
    j = job()
    monkeypatch.setattr(command_job_state, 'read', lambda _: j)
    monkeypatch.setattr(command_job_state, 'change', lambda _, fn: fn(j))
    monkeypatch.setattr(OutboundMessageService, '__init__', lambda self: None)
    monkeypatch.setattr(OutboundMessageService, 'get', lambda *a: dict(source_room_id='other'))
    for result in ({'success':False}, {'success':True, 'proposal_id':'p'}):
        await observe('j', 'compose_message', {'action':'propose'}, result)
        assert 'proposal_preview' not in j
