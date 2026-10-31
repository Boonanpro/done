from concurrent.futures import ThreadPoolExecutor
import uuid
import pytest
from app.services import command_job_state as state
from app.services.voice_job_followup import prepare

@pytest.fixture
def parent(tmp_path, monkeypatch):
    monkeypatch.setattr(state, 'ROOT', tmp_path)
    key = str(uuid.uuid4())
    state.create(key, user_id='owner', origin_room_id='room', room_id='target',
                 origin_project_id='project', engine='make', model='astra', queue_owner='process',
                 state='completed', task='Shorten /tmp/memo. Keep 20 seats.', result='Saved /tmp/memo.',
                 approved='old', confirmation={'id':'old'}, run_id='old-run', runner_process=123)
    return key

def follow(key, **kw):
    return prepare(key, kw.get('user', 'owner'), kw.get('room', 'room'),
                   kw.get('instruction', 'Make it free.'), [{'role':'user','text':'Make it free.'}])

def test_preserves_target_and_conditions_without_reusing_execution_or_approval(parent):
    before = state.read(parent)
    child = follow(parent)
    assert state.read(parent) == before
    assert child['room_id'] == 'target' and child['origin_room_id'] == 'room'
    assert child['engine'] == 'make' and child['model'] == 'astra'
    assert child['state'] == 'queued' and child['previous_job_id'] == parent
    assert '/tmp/memo' in child['task'] and '20 seats' in child['task']
    assert not {'approved', 'confirmation', 'run_id', 'runner_process'} & child.keys()

@pytest.mark.parametrize('key,value', [('user','foreign'), ('room','foreign')])
def test_foreign_context_rejected(parent,key,value):
    with pytest.raises(ValueError): follow(parent, **{key:value})
    assert len(list(state.ROOT.glob('*.json'))) == 1

@pytest.mark.parametrize('status', ['cancelled','failed','paused','running'])
def test_does_not_resume_stopped_or_unfinished_work(parent,status):
    state.change(parent, lambda s:s.update(state=status))
    with pytest.raises(ValueError): follow(parent)
    assert len(list(state.ROOT.glob('*.json'))) == 1

def test_concurrent_duplicate_creates_only_one_successor(parent):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _:follow(parent),range(4)))
    assert len({r['id'] for r in results}) == 1
    assert len(list(state.ROOT.glob('*.json'))) == 2
    child = results[0]
    state.control(child['id'],'owner','room','cancel')
    assert follow(parent)['state'] == 'cancelled'
    assert len(list(state.ROOT.glob('*.json'))) == 2

def test_different_edit_does_not_fork_same_artifact(parent):
    follow(parent)
    with pytest.raises(ValueError): follow(parent,instruction='Make it 100 yen.')
    assert len(list(state.ROOT.glob('*.json'))) == 2

def test_long_context_is_rejected_without_truncation(parent):
    state.change(parent,lambda s:s.update(task='x'*64000))
    with pytest.raises(ValueError): follow(parent)
    assert len(list(state.ROOT.glob('*.json'))) == 1

@pytest.mark.asyncio
async def test_voice_completed_update_returns_new_target_without_status_round_trip(parent, monkeypatch):
    from unittest.mock import AsyncMock
    from app.services import command_center, voice_responses
    wake = AsyncMock()
    monkeypatch.setattr(command_center, '_wake_job', wake)
    out = await voice_responses.run_function('steer_job', {'job_id':parent, 'kind':'update',
        'instruction':'Make it free.'}, 'owner', 'room', [{'role':'user','text':'Make it free.'}])
    assert out['accepted'] and out['job_id'] != parent and not out['delivered']
    assert out['previous_job_id'] == parent
    wake.assert_awaited_once_with(out['job_id'])
    state.control(out['job_id'], 'owner', 'room', 'cancel')
    retry = await voice_responses.run_function('steer_job', {'job_id':parent, 'kind':'update',
        'instruction':'Make it free.'}, 'owner', 'room', [{'role':'user','text':'Make it free.'}])
    assert not retry['accepted'] and retry['state'] == 'cancelled'
    assert wake.await_count == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('operation',['pause','cancel','resume'])
async def test_completed_non_edit_does_not_start_work(parent, monkeypatch, operation):
    from unittest.mock import AsyncMock
    from app.services import command_center, voice_responses
    wake = AsyncMock()
    monkeypatch.setattr(command_center,'_wake_job',wake)
    out = await voice_responses.run_function('steer_job',{'job_id':parent,'kind':operation},'owner','room',[])
    assert not out.get('accepted')
    wake.assert_not_awaited()
    assert len(list(state.ROOT.glob('*.json'))) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('claimed',[False, True])
async def test_wake_timeout_never_replays_or_fails_claimed_job(parent, monkeypatch, claimed):
    from app.services import command_center
    from app.services.voice_job_followup import continue_completed
    async def wake(key):
        if claimed: state.change(key,lambda s:s.update(accepted_at=state.now()))
        raise TimeoutError()
    monkeypatch.setattr(command_center,'_wake_job',wake)
    out = await continue_completed(parent,'owner','room','Make it free.',[])
    assert out['accepted'] == claimed
    assert out['state'] == ('queued' if claimed else 'failed')
    assert len(list(state.ROOT.glob('*.json'))) == 2
