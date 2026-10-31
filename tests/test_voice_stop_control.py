import asyncio
from unittest.mock import AsyncMock
import pytest
from app.services.voice_stop_control import StopControl, explicit_stop


@pytest.mark.parametrize('text', ['一旦その作業を止めて。', 'いったんその作業を止めて', '今の作業を中止してください'])
def test_explicit_request(text):
    assert explicit_stop(text)


@pytest.mark.parametrize('text', ['その作業を止めてとは言ってない', '作業を止めてもいい？', '止めて', '音声を止めて', '作業を止めて、いや続けて', '別室の作業を止めて'])
def test_ambiguous_or_negated(text):
    assert not explicit_stop(text)


@pytest.mark.asyncio
async def test_only_current_call_job_can_be_stopped(monkeypatch):
    from app.services import command_job_state as s
    stopped=[]
    job={'id':'job-a','room_id':'room','created_at':'2026-11-01T00:00:02+00:00','state':'running'}
    monkeypatch.setattr(s,'list_owned',lambda *args:[job])
    monkeypatch.setattr(s,'control',lambda *args:stopped.append(args))
    c=StopControl('owner','room','2026-11-01T00:00:00+00:00',AsyncMock(),lambda *a,**k:None)
    await c.stop_one(); await c.stop_one()
    assert stopped == [('job-a','owner','room','cancel')]
    assert '停止済み' in c.send.call_args.args[0]['content']
    assert '確認前' in c.send.call_args.args[0]['content']


@pytest.mark.asyncio
@pytest.mark.parametrize('case',['other_room','older','multiple','completed','truncated'])
async def test_does_not_stop_unrelated_or_ambiguous_jobs(monkeypatch,case):
    from app.services import command_job_state as s
    job={'id':'job-a','room_id':'room','created_at':'2026-11-01T00:00:02+00:00','state':'running'}
    if case=='other_room':job['room_id']='elsewhere'
    if case=='older':job['created_at']='2026-10-31T00:00:00+00:00'
    if case=='completed':job['state']='completed'
    jobs=[job,dict(job,id='job-b')] if case=='multiple' else [job]
    monkeypatch.setattr(s,'list_owned',lambda *args:jobs)
    if case=='truncated': jobs.extend(dict(job,id=str(i),state='completed') for i in range(19))
    stopped=[]
    monkeypatch.setattr(s,'control',lambda *args:stopped.append(args))
    c=StopControl('owner','room','2026-11-01T00:00:00+00:00',AsyncMock(),lambda *a,**k:None)
    await c.stop_one()
    assert stopped == []
    c.send.assert_not_called()


@pytest.mark.asyncio
async def test_continuing_negation_cancels_pending_stop():
    c=StopControl('u','r','2026-11-01T00:00:00+00:00',AsyncMock(),lambda *a,**k:None)
    c.stop_one=AsyncMock()
    c.heard('その作業を止めて',0,500)
    c.heard('とは言ってない',500,1000)
    await asyncio.sleep(1.3)
    c.stop_one.assert_not_called()
    c.close()
