import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services import work_continuity as w


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(w, 'DB', tmp_path / 'work.sqlite')
    monkeypatch.setenv('DAN_WORK_DB', str(w.DB))
    monkeypatch.setattr(w, '_tasks', {})


def add(key='one', room='room', goal='資料を完成する'):
    return w.enqueue(key=key, room_id=room, user_id='owner', source='test', prompt=goal,
                     goal=goal, authority='本人が資料作成を依頼', criteria='資料を開いて内容を確認')


def test_duplicate_and_concurrent_claim():
    add()
    add(goal='上書きされない')
    with ThreadPoolExecutor(6) as pool:
        claims = list(pool.map(lambda _: w.claim('one'), range(6)))
    assert len([r for r in claims if r]) == 1
    assert w.get('one')['goal'] == '資料を完成する'
    add('two')
    assert w.claim('two') is None


def test_cross_room_and_stale_checkpoint():
    add()
    row = w.claim('one')
    with pytest.raises(ValueError):
        w.checkpoint('one', 'other', status='done', evidence='確認済み')
    with pytest.raises(ValueError):
        w.checkpoint('one', 'room', status='done', evidence='確認済み')
    w.checkpoint('one', 'room', token=row['token'], status='done', evidence='資料を開いて内容確認')
    assert w.claim('one') is None
    w.finish('one', row['token'])
    assert w.get('one')['status'] == 'done'


def test_evidence_and_resumption_condition_required():
    add()
    with pytest.raises(ValueError):
        w.checkpoint('one', 'room', status='done', evidence='')
    with pytest.raises(ValueError):
        w.checkpoint('one', 'room', status='waiting', evidence='承認待ち')
    w.checkpoint('one','room',status='waiting',evidence='送信案を用意',next_step='本人が送信を承認したら送る')
    assert w.claim('one') is None


def test_turn_end_is_not_completion_and_retry_is_bounded():
    add()
    for number in range(3):
        with w.connection() as db:
            db.execute('UPDATE work SET wake_at=0')
        row = w.claim('one')
        w.finish('one', row['token'])
        assert w.get('one')['status'] == ('ready' if number < 2 else 'blocked')
    assert w.claim('one') is None


def test_recovery_only_dead_process_and_no_replay():
    add()
    row = w.claim('one')
    w.recover()
    assert w.get('one')['status'] == 'running'
    with w.connection() as db:
        db.execute('UPDATE work SET pid=999999999')
    w.recover()
    recovered = w.get('one')
    assert recovered['status'] == 'ready'
    assert '再送しない' in recovered['next_step']
    row = w.claim('one')
    w.checkpoint('one','room',token=row['token'],status='done',evidence='保存先を確認')
    with w.connection() as db:
        db.execute('UPDATE work SET pid=999999999')
    w.recover()
    assert w.get('one')['status'] == 'done'


def test_stop_cancels_queued_and_running_but_not_other_room():
    add()
    row = w.claim('one')
    add('two')
    add('other','other-room')
    w.cancel_room('room','owner')
    w.finish('one',row['token'],failed=True)
    assert w.get('one')['status'] == w.get('two')['status'] == 'cancelled'
    assert w.get('other')['status'] == 'ready'


def runtime(monkeypatch, runner):
    import app.agent.cli_runner as cr
    import app.services.followup_poller as fp
    monkeypatch.setattr(cr,'process_message_cli',runner)
    monkeypatch.setattr(fp,'_room_busy',lambda room: False)
    monkeypatch.setattr(fp,'_resolve_project_id',lambda room: None)
    async def busy(room):
        return fp._room_busy(room)
    monkeypatch.setattr(w, 'room_busy', busy)


def test_receipt_to_saved_artifact_and_checkpoint(monkeypatch, tmp_path):
    artifact = tmp_path / '撮影案.txt'
    async def runner(**args):
        row = w.get('one')
        assert '新たな費用・外部送信・公開の権限は増えない' in args['content']
        artifact.write_text('届いた部屋の写真を基に撮影場所の案を用意',encoding='utf-8')
        w.checkpoint('one','room',token=row['token'],status='done',evidence=str(artifact)+':内容確認済み')
        yield {'type':'result','text':'撮影案を作りました。'}
    runtime(monkeypatch,runner)
    asyncio.run(w.execute(key='one',room_id='room',user_id='owner',prompt='写真が届いた'))
    assert artifact.exists() and w.get('one')['status'] == 'done'


def test_failure_not_retried_or_completed(monkeypatch):
    async def runner(**args):
        yield {'type':'error','message':'認証失敗'}
        yield {'type':'result','text':'完了'}
    runtime(monkeypatch,runner)
    asyncio.run(w.execute(key='one',room_id='room',user_id='owner',prompt='作業'))
    assert w.get('one')['status'] == 'blocked'


def test_busy_receipt_is_durable(monkeypatch):
    import app.services.followup_poller as fp
    runtime(monkeypatch,None)
    monkeypatch.setattr(fp,'_room_busy',lambda room: True)
    result = asyncio.run(w.execute(key='one',room_id='room',user_id='owner',prompt='受信'))
    assert result == ('',False)
    assert w.get('one')['status'] == 'ready' and w.get('one')['attempts'] == 0


def test_private_work_and_timed_wait_use_same_dispatch(monkeypatch):
    add(goal='私用の外出に必要な持ち物を準備')
    w.checkpoint('one','room',status='waiting',evidence='出発日の前日まで待つ',next_step='持ち物を確認',wake_at=time.time()-1)
    async def runner(**args):
        row = w.get('one')
        assert '私用の外出' in args['content']
        w.checkpoint('one','room',token=row['token'],status='done',evidence='持ち物一覧と予定を照合済み')
        yield {'type':'result','text':'準備完了'}
    runtime(monkeypatch,runner)
    monkeypatch.setattr('app.services.restart_signal.draining',lambda: False)
    monkeypatch.setattr(w,'notify_blocked',AsyncMock())
    async def run():
        await w.dispatch()
        await asyncio.gather(*list(w._tasks.values()))
    asyncio.run(run())
    assert w.get('one')['status'] == 'done'


def test_checkpoint_command_from_real_process(tmp_path):
    add()
    row=w.claim('one')
    data={'action':'checkpoint','id':'one','token':row['token'],'status':'done',
          'evidence':'確認した成果物: /tmp/result.txt'}
    result=subprocess.run([sys.executable,'scripts/work_checkpoint.py','--room','room'],
        input=json.dumps(data),text=True,capture_output=True,
        env={**os.environ,'DAN_ROOM_ID':'room'})
    assert result.returncode == 0, result.stderr
    assert w.get('one')['status'] == 'done'
    result=subprocess.run([sys.executable,'scripts/work_checkpoint.py','--room','other'],
        input=json.dumps(data),text=True,capture_output=True,
        env={**os.environ,'DAN_ROOM_ID':'room'})
    assert result.returncode != 0


def test_assembled_context_refresh_and_reseed_keep_work(monkeypatch):
    from app.agent import cli_runner as cr
    from app.agent.codex_runner import wrap_turn_content
    sb=MagicMock()
    sb.table.return_value=sb
    for method in ('select','eq','order','limit'):
        getattr(sb,method).return_value=sb
    sb.execute.return_value.data=[]
    monkeypatch.setattr('app.services.supabase_client.get_supabase_client',lambda: type('C',(),{'client':sb})())
    monkeypatch.setattr(cr,'_place_block',lambda *args:'<place>場所</place>')
    add()
    first=cr._build_room_state_context('room',max_chars=200)
    assert '資料を完成する' in first and first.count('<work_continuity>') == 1
    w.checkpoint('one','room',status='waiting',evidence='台本が保存された',next_step='本人の感想が届いたら改稿')
    second=cr._build_room_state_context('room',max_chars=200)
    assert '本人の感想' in second and '台本が保存された' in second
    assert '本人の感想' in wrap_turn_content('',second)
    recovered=cr._build_reseed_context('room',max_chars=200)
    assert '本人の感想' in recovered and recovered.count('<work_continuity>') == 1
    assert '資料を完成する' not in cr._build_room_state_context('other',max_chars=200)


def test_official_line_followup_is_transferred_to_work(monkeypatch):
    import app.services.followup_poller as fp
    statuses=[]
    async def runner(**args):
        assert '公式LINE' in args['content']
        yield {'type':'result','text':'確認しました'}
    runtime(monkeypatch,runner)
    monkeypatch.setattr(fp,'_discard_no_change_report',AsyncMock(return_value=True))
    monkeypatch.setattr('app.services.followups.mark_status',lambda key,status: statuses.append((key,status)))
    asyncio.run(fp._fire_at({'id':'line-event','room_id':'room','user_id':'owner',
                            'plain_note':'公式LINEで写真が届いた','spec':{}}))
    row=w.get(w.key_for('followup','room','line-event'))
    assert statuses == [('line-event','done')]
    assert row['status'] == 'ready'  # Delivery finished, actual work did not.


def test_stop_wins_over_late_checkpoint():
    add()
    row=w.claim('one')
    w.cancel_room('room','owner')
    with pytest.raises(ValueError):
        w.checkpoint('one','room',token=row['token'],status='ready',evidence='作業の途中',next_step='続ける')
    w.finish('one',row['token'])
    assert w.get('one')['status'] == 'cancelled'


def test_new_progress_resets_no_progress_limit():
    add()
    for i in range(5):
        with w.connection() as db:
            db.execute('UPDATE work SET wake_at=0')
        row=w.claim('one')
        w.checkpoint('one','room',token=row['token'],status='ready',evidence=f'成果物{i}を確認',next_step='次の章を書く')
        w.finish('one',row['token'])
        assert w.get('one')['status'] == 'ready'


def test_failure_notice_is_delivered_once(monkeypatch):
    add()
    row=w.claim('one')
    w.finish('one',row['token'],failed=True)
    send=AsyncMock()
    monkeypatch.setattr('app.services.chat_service.ChatService',lambda: type('S',(),{'send_message':send})())
    asyncio.run(w.notify_blocked())
    asyncio.run(w.notify_blocked())
    assert send.call_count == 1
    assert send.call_args.kwargs['message_id']


def test_inbound_schedule_saves_before_running(monkeypatch):
    from app.services import inbound_wakeup as inbound
    runtime(monkeypatch,None)
    monkeypatch.setattr('app.services.followup_poller._room_busy',lambda room: True)
    message={'id':'receipt','user_id':'owner','source':'email','content':'依頼の素材が届きました'}
    async def run():
        assert inbound.schedule_room_wakeup(message,'room',reason='案件一致')
        key=w.key_for('inbound:email','room','receipt')
        assert w.get(key)['status'] == 'ready'
        await asyncio.gather(*list(inbound._tasks))
        assert w.get(key)['status'] == 'ready'
    asyncio.run(run())
