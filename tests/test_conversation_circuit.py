"""The drawing must come from this request and the preview must stop before dispatch."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import conversation_circuit as circuit, prompt_store, voice_router


def test_call_only_links_its_own_job(tmp_path, monkeypatch):
    from app.services import voice_sideband
    log = tmp_path / 'voice-sideband.jsonl'
    monkeypatch.setattr(voice_sideband, 'LOG', log)
    monkeypatch.setattr(circuit, 'LIVE_ROOT', tmp_path)
    rows = [
        dict(at='01', room_id='a', session_id='one', phase='speech_start', side='owner'),
        dict(at='02', room_id='b', session_id='two', phase='route_chosen', route='app'),
        dict(at='03', room_id='a', session_id='one', phase='route_chosen', route='make', ms=180),
        dict(at='04', room_id='a', session_id='one', phase='route_job_started', job_id='deadbeef'),
    ]
    log.write_text('\n'.join(json.dumps(r) for r in rows))
    jobs = [dict(id='deadbeef-1', created_at='05', task='字幕を大きく', events=[]),
            dict(id='unused', created_at='05', task='別件', events=[])]
    observed = circuit.voice_steps(circuit.voice_records('a')['one'], jobs)
    assert [s['node'] for s in observed] == ['owner','router','parallel','parallel']
    assert observed[1]['ms'] == 180 and observed[-1]['detail'] == '字幕を大きく'


@pytest.mark.asyncio
async def test_voice_preview_prepares_real_task_without_starting(monkeypatch):
    from app.api import conversation_circuit as api
    from app.services import command_center, voice_editor
    monkeypatch.setattr(api, 'check_room', AsyncMock())
    monkeypatch.setattr(voice_router.Router, 'targets_now', AsyncMock(return_value={}))
    monkeypatch.setattr(voice_router.Router, 'route', AsyncMock(return_value=('make','','',.95,160)))
    monkeypatch.setattr(voice_editor, 'call_editor', lambda room: None)
    dispatch = AsyncMock()
    monkeypatch.setattr(command_center, 'execute', dispatch)
    words = 'この場面を長くして'
    result = await api.preview(api.Trial(room='r', channel='voice', words=words), 'u')
    assert result[-1]['detail'].startswith('今回のユーザー発言（原文）:\n'+words)
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_sdp_never_registers_room_or_attaches_worker(monkeypatch):
    from app.api import voicelog_routes as api
    from app.services import owner, room_files, voice_editor, voice_live, voice_sideband
    chat = MagicMock(get_room=AsyncMock(return_value={'id':'r'}), get_messages=AsyncMock(return_value=[]))
    monkeypatch.setattr(api,'ChatService',lambda:chat)
    monkeypatch.setattr(api,'_get_user',lambda _:SimpleNamespace(user_id='u'))
    monkeypatch.setattr(owner,'resolve_owner_user_id',lambda:'u')
    monkeypatch.setattr(room_files,'listing',AsyncMock(return_value=[]))
    monkeypatch.setattr(voice_editor,'call_editor',lambda _:None)
    monkeypatch.setattr(voice_live,'session_config',lambda *a,**k:{'model':'v','delegation':{'type':'responses'},'_backend':{'tools':['work']}})
    monkeypatch.setattr(api.settings,'OPENAI_API_KEY','test')
    guards = [MagicMock() for _ in range(3)]
    monkeypatch.setattr(voice_live,'register',guards[0])
    monkeypatch.setattr(voice_live,'bind_session',guards[1])
    monkeypatch.setattr(voice_sideband,'attach',guards[2])
    client = AsyncMock()
    client.post.return_value = MagicMock(status_code=201,json=lambda:{'session':{'id':'s'},'transport':{'sdp':'answer'}})
    context = AsyncMock()
    context.__aenter__.return_value=client
    monkeypatch.setattr(api.httpx,'AsyncClient',lambda **kw:context)
    result = await api.create_preview_session(None,api.LiveSessionRequest(sdp='offer',room_id='r'))
    assert result['preview_only']
    config = client.post.await_args.kwargs['json']['session']
    assert config['delegation']['type']=='client' and '_backend' not in config
    for guard in guards:
        guard.assert_not_called()



def test_job_tool_event_keeps_activity_and_elapsed_time():
    from app.services.command_job_state import event
    job = dict(created_at='01', task='字幕を直して', events=[])
    event(job, 'tool', 'browser', activity='字幕の大きさを確認しています', ms=820)
    event(job, 'tool', 'read_file')
    received, browser, document = circuit.job_steps(job)
    assert received['handoff'] == job['task']
    assert (browser['activity'], browser['ms']) == ('字幕の大きさを確認しています', 820)
    assert document['activity'] == '資料を読んでいます'


def test_old_job_events_with_tool_names_get_readable_labels():
    job = dict(created_at='01', task='前の会話を確認', events=[dict(at='02', kind='tool', text='lookup')])
    assert circuit.job_steps(job)[1]['activity'] == '記録を見ています'
