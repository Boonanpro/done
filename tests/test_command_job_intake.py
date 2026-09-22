import asyncio
import uuid
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.requests import Request
from app.services import command_job_state as state
from app.core.api import command_job_routes as routes


@pytest.fixture
def job(tmp_path,monkeypatch):
    monkeypatch.setattr(state,'ROOT',tmp_path)
    key=str(uuid.uuid4())
    state.create(key,queue_owner='core',user_id='owner',room_id='target',
        origin_room_id='hub',origin_project_id='project',task='read only')
    return key


@pytest.mark.asyncio
async def test_local_intake_acknowledges_without_shared_watch_database(job,monkeypatch):
    from app.services import command_job_runner as runner
    from app.services.chat_service import ChatService
    monkeypatch.setattr(routes.browser_lifecycle,'authorized',lambda value:True)
    db=Mock(side_effect=AssertionError('Local intake must not touch shared watch database'))
    monkeypatch.setattr(ChatService,'__init__',db)
    dispatch=Mock()
    monkeypatch.setattr(runner,'dispatch',dispatch)
    request=Request({'type':'http','method':'POST','path':'/','headers':[], 'client':('127.0.0.1',123)})
    result=await routes.wake(routes.Wake(job_id=job),request)
    assert result['accepted']
    assert state.read(job)['accepted_at']
    assert dispatch.call_args.args[0]['spec']['task']=='read only'
    db.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_wakes_share_one_running_task(job,monkeypatch):
    from app.services import command_job_runner as runner
    gate=asyncio.Event()
    run=AsyncMock(side_effect=lambda row:None)
    async def hold(row):
        await run(row)
        await gate.wait()
    monkeypatch.setattr(runner,'run',hold)
    first=runner.dispatch({'id':job})
    second=runner.dispatch({'id':job})
    assert first is second
    await asyncio.sleep(0)
    run.assert_awaited_once()
    gate.set()
    await first
    runner._tasks.pop(job)


@pytest.mark.asyncio
async def test_recovery_requeues_only_unstarted_local_work(job,monkeypatch):
    from app.services import command_job_runner as runner
    dispatch=Mock()
    monkeypatch.setattr(runner,'dispatch',dispatch)
    await runner.recover()
    assert dispatch.call_args.args[0]['id']==job


def test_local_completion_does_not_update_shared_watch(job,monkeypatch):
    from app.services import command_job_runner as runner,followups
    update=Mock(side_effect=AssertionError('must not touch watch'))
    monkeypatch.setattr(followups,'mark_status',update)
    runner.mark_status(job,'done')
    update.assert_not_called()


@pytest.mark.asyncio
async def test_completed_report_retry_keeps_execution_identity(job,monkeypatch):
    from app.services import command_job_runner as runner
    state.change(job,lambda s:s.update(state='completed',run_id='original-run',result='42'))
    runner.mark_status(job,'pending')
    dispatch=Mock()
    monkeypatch.setattr(runner,'dispatch',dispatch)
    await runner.dispatch_pending()
    assert dispatch.call_args.args[0]['id']==job
    assert state.read(job)['run_id']=='original-run'
    runner.mark_status(job,'done')
    dispatch.reset_mock()
    await runner.dispatch_pending()
    dispatch.assert_not_called()
