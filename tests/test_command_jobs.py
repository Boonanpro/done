import asyncio
import uuid
from unittest.mock import AsyncMock
import pytest
from app.services import command_job_state as s
from app.services import command_job_tools as gate

@pytest.fixture
def job(tmp_path,monkeypatch):
    monkeypatch.setattr(s,'ROOT',tmp_path)
    key=str(uuid.uuid4())
    s.create(key,user_id='owner',origin_room_id='hub',task='test',state='running')
    return key

def test_foreign_owner_cannot_control_job(job):
    with pytest.raises(ValueError):s.control(job,'other','hub','cancel')
    assert s.read(job)['state']=='running'

def test_windows_reader_collision_retries_save_not_control(job,monkeypatch):
    original=s.os.replace
    calls=[]
    def replace(a,b):
        calls.append(1)
        if len(calls)==1:raise PermissionError('reader has destination open')
        return original(a,b)
    monkeypatch.setattr(s.os,'replace',replace)
    s.control(job,'owner','hub','update','Change the date')
    saved=s.read(job)
    assert saved['revision']==1 and len(saved['inputs'])==1
    assert len(saved['events'])==1 and len(calls)==2

@pytest.mark.asyncio
async def test_project_lookup_failure_finishes_job_instead_of_leaving_it_queued(job,monkeypatch):
    from app.services import command_job_runner as runner
    from app.services.project_service import ProjectService
    from app.services import followups
    monkeypatch.setattr(ProjectService,'get_project_by_room_id',AsyncMock(side_effect=RuntimeError('database unavailable')))
    statuses=[]
    monkeypatch.setattr(followups,'mark_status',lambda key,status:statuses.append(status))
    await runner.run({'id':job,'user_id':'owner','room_id':'target','spec':{'origin_room_id':'hub','origin_project_id':'p','task':'test'}})
    assert s.read(job)['state']=='failed'
    assert 'database unavailable' in s.read(job)['error']
    assert statuses==['failed']

def test_reuse_idle_browser_but_isolate_parallel_jobs(job):
    room=s.browser_room(job)
    second=str(uuid.uuid4());s.create(second,user_id='owner',origin_room_id='hub',state='running')
    assert s.browser_room(second)!=room
    s.publish(job,'result','done',state='completed')
    third=str(uuid.uuid4());s.create(third,user_id='owner',origin_room_id='hub',state='running')
    assert s.browser_room(third)==room
    foreign=str(uuid.uuid4());s.create(foreign,user_id='other',origin_room_id='hub',state='running')
    assert s.browser_room(foreign)!=room

@pytest.mark.asyncio
@pytest.mark.parametrize('label,body',[
    ('SMS送信','ワンタイムパスワードをご登録済みの電話番号に送信します'),
    ('OK 次へ','ワンタイムパスワード入力'),
    ('予約確認/変更/払戻\n予約件数1件','メニュー'),
    ('購入履歴','合計14920円'),
    ('次へ','座席を選択 合計14920円'),
])
async def test_navigation_and_own_login_do_not_wait(job,monkeypatch,label,body):
    monkeypatch.setattr(gate,'browser_target',AsyncMock(return_value={'url':'https://example.com','label':label,'body':body}))
    await asyncio.wait_for(gate.guard(job,'browser',{'action':'click','ref':'@test'}),.5)
    assert not s.read(job).get('confirmation')

@pytest.mark.parametrize('label,body',[
    ('SMS送信','決済の認証 ワンタイムパスワード'),
    ('送信','宛先: お客様 メッセージ本文'),
    ('購入を確定','14920円'),('払戻を確定','返金14600円'),
    ('投稿する','公開範囲 全員'),('削除','完全に削除'),
])
def test_irreversible_actions_still_require_confirmation(label,body):
    assert gate.needs_confirmation({'label':label,'body':body})

def test_conditions_invalidate_old_confirmation(job):
    def waiting(v):
        v.update(state='awaiting_confirmation', confirmation={'id':'old','revision':0,'fingerprint':'x'})
    s.change(job,waiting)
    s.control(job,'owner','hub','update','First tell me the car number')
    with pytest.raises(ValueError):s.control(job,'owner','hub','confirm',confirmation_id='old')
    assert s.read(job)['applied_revision']==0 and s.read(job)['revision']==1

@pytest.mark.asyncio
async def test_pause_blocks_next_tool_until_resume_is_applied(job):
    s.control(job,'owner','hub','pause')
    task=asyncio.create_task(gate.available(job))
    await asyncio.sleep(.15)
    assert not task.done()
    s.control(job,'owner','hub','resume')
    await asyncio.sleep(.15)
    assert not task.done()
    s.change(job,lambda v:v.update(applied_revision=v['revision']))
    await asyncio.wait_for(task,1)

@pytest.mark.skip(reason='The approval gate for voice-delegated jobs was abolished on 2026-09-22 (owner: same authority as chat Dan). Kept as the record of what the gate did.')
@pytest.mark.asyncio
async def test_checkout_requires_one_use_approval_and_rechecks_page(job,monkeypatch):
    page={'url':'https://example.com/checkout','label':'購入を確定','type':'submit','body':'14号車11E 合計14920円'}
    monkeypatch.setattr(gate,'browser_target',AsyncMock(return_value=page))
    with pytest.raises(gate.ConfirmationPending):
        await asyncio.wait_for(gate.guard(job,'browser',{'action':'click','ref':'@buy'}),.5)
    proposal=s.read(job)['confirmation']
    assert proposal['created_at']
    s.control(job,'owner','hub','confirm',confirmation_id=proposal['id'])
    assert '本人の承認' in await gate.guard(job,'browser',{'action':'click','ref':'@buy'})
    assert 'approved' not in s.read(job)
    # A repeated checkout cannot consume the same grant a second time.
    with pytest.raises(gate.ConfirmationPending):
        await gate.guard(job,'browser',{'action':'click','ref':'@buy'})

@pytest.mark.skip(reason='The approval gate for voice-delegated jobs was abolished on 2026-09-22 (owner: same authority as chat Dan). Kept as the record of what the gate did.')
@pytest.mark.asyncio
async def test_changed_price_prevents_checkout(job,monkeypatch):
    first={'url':'https://example.com','label':'購入確定','type':'submit','body':'14920円'}
    monkeypatch.setattr(gate,'browser_target',AsyncMock(side_effect=[first,{**first,'body':'20000円'}]))
    with pytest.raises(gate.ConfirmationPending):
        await gate.guard(job,'browser',{'action':'click','ref':'@buy'})
    s.control(job,'owner','hub','confirm',confirmation_id=s.read(job)['confirmation']['id'])
    with pytest.raises(gate.ConfirmationPending):await gate.guard(job,'browser',{'action':'click','ref':'@buy'})
    assert s.read(job)['state']=='awaiting_confirmation'
    assert not s.read(job).get('approved')

@pytest.mark.skip(reason='The approval gate for voice-delegated jobs was abolished on 2026-09-22 (owner: same authority as chat Dan). Kept as the record of what the gate did.')
@pytest.mark.asyncio
async def test_arbitrary_browser_script_cannot_bypass_confirmation(job):
    with pytest.raises(RuntimeError,match='JavaScript'):
        await gate.guard(job,'browser',{'action':'evaluate','expression':'fetch("/buy", {method:"POST"})'})
    # reading with JavaScript is allowed (2026-09-22): only scripts that commit something stay closed
    await gate.guard(job,'browser',{'action':'evaluate','expression':'document.title'})

@pytest.mark.skip(reason='The approval gate for voice-delegated jobs was abolished on 2026-09-22 (owner: same authority as chat Dan). Kept as the record of what the gate did.')
@pytest.mark.asyncio
async def test_separate_jobs_do_not_wait_on_each_others_confirmation(job):
    other=str(uuid.uuid4());s.create(other,user_id='owner',origin_room_id='hub',state='running')
    with pytest.raises(gate.ConfirmationPending):await gate.propose(job,'buy?', 'digest')
    await asyncio.wait_for(gate.available(other),.5)
    await asyncio.wait_for(gate.guard(job,'browser',{'action':'get_state'}),.5)
    with pytest.raises(gate.ConfirmationPending):await gate.available(job)

def test_smartex_list_navigation_is_not_final_refund():
    target={'url':'https://shinkansen2.jr-central.co.jp/RSV_P/p74/ClientService','label':'払戻',
        'body':'予約確認/変更/払戻\nSTEP\n予約一覧\n予約件数：1件',
        'onclick':"cfEXPY_doAction('RSWP230AIDP004');return false;"}
    assert not gate.needs_confirmation(target)
    assert gate.needs_confirmation({**target,'onclick':"cfEXPY_doAction('OTHER');"})
    assert gate.needs_confirmation({**target,'url':'https://example.com/RSV_P/p74/ClientService'})
    assert gate.needs_confirmation({**target,'body':'払戻内容確認\n返金額10000円'})
