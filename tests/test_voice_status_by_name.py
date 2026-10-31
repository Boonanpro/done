"""Named cross-room status: no relay, no job launch, and no ambiguous selection."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.services import command_center as cc, voice_responses as vr
from app.services.project_service import ProjectService

@pytest.mark.asyncio
@pytest.mark.parametrize('count', [0, 1, 2])
async def test_named_status_through_voice(monkeypatch, count):
    chat, projects, runs = AsyncMock(), AsyncMock(), AsyncMock()
    chat.get_room.return_value = {'id': 'room'}
    candidates = [{'id': f'p{i}', 'room_id': f'r{i}', 'title': '開発室'} for i in range(count)]
    projects.find_status_projects.return_value = candidates
    projects.get_project.return_value = candidates[0] if candidates else None
    runs.get_current_run.return_value = {'id': 'actual-run', 'state': 'running'}
    projects.get_execution_events.return_value = [{'content': '文章を編集しています'}]
    monkeypatch.setattr(cc, 'ChatService', lambda: chat)
    monkeypatch.setattr(cc, 'ProjectService', lambda: projects)
    monkeypatch.setattr('app.services.run_service.RunService', lambda: runs)
    wake = AsyncMock()
    monkeypatch.setattr(cc, '_wake_job', wake)
    out = await vr.run_function('job_status', {'query': '開発室'}, 'owner', 'call-room', [])
    projects.find_status_projects.assert_awaited_once_with('owner', '開発室')
    if count == 1:
        assert out['run']['id'] == 'actual-run'
        assert out['activity'][0]['content'] == '文章を編集しています'
        projects.get_project.assert_awaited_once_with('p0', 'owner')
        chat.get_room.assert_any_await('r0', 'owner')
    else:
        assert out['resolved'] is False and out['count'] == count
        runs.get_current_run.assert_not_awaited()
    chat.send_message.assert_not_awaited()
    wake.assert_not_awaited()

@pytest.mark.asyncio
async def test_named_status_rechecks_room_access(monkeypatch):
    chat, projects = AsyncMock(), AsyncMock()
    chat.get_room.side_effect = [{'id': 'call-room'}, None]
    projects.find_status_projects.return_value = [{'id': 'p'}]
    projects.get_project.return_value = {'id': 'p', 'room_id': 'other'}
    monkeypatch.setattr(cc, 'ChatService', lambda: chat)
    monkeypatch.setattr(cc, 'ProjectService', lambda: projects)
    with pytest.raises(ValueError, match='アクセス権'):
        await cc.execute({'action': 'status', 'query': '開発室'}, 'call-room', 'owner')

@pytest.mark.asyncio
async def test_lookup_keeps_hidden_branches_and_filters_owner():
    service = object.__new__(ProjectService)
    db = MagicMock()
    service.supabase = db
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(data=[
        {'id': 'branch', 'title': '音声の枝', 'room_id': 'r', 'user_id': 'owner', 'metadata': {'hidden': True}},
        {'id': 'foreign', 'title': '音声の枝', 'room_id': 'f', 'user_id': 'other'},
        {'id': 'similar', 'title': '古い音声の枝', 'room_id': 's', 'user_id': 'owner'},
    ])
    out = await service.find_status_projects('owner', ' 音声の枝 ')
    assert [p['id'] for p in out] == ['branch']
    db.table.return_value.select.return_value.eq.assert_called_once_with('user_id', 'owner')
    with pytest.raises(ValueError):
        await service.find_status_projects('owner', ' ')

def test_session_exposes_named_status(monkeypatch):
    from app.services import voice_live
    monkeypatch.setattr('app.services.dan_core.shared', lambda *a: '共通の指示')
    session = voice_live.session_config(room_id='room', user_id='owner')
    backend = session['delegation']['responses']
    assert 'queryに部屋名' in backend['instructions']
    schema = next(t for t in vr.TOOLS if t.get('name') == 'job_status')
    assert 'query' in schema['parameters']['properties']
