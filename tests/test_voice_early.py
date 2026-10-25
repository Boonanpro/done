import asyncio
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services import voice_prefetch as P, voice_sideband as S, voice_responses as R


@pytest.fixture
def reads(monkeypatch):
    calls = []
    async def run(name, args, uid, rid, dialogue, **kw):
        calls.append((name, args, uid, rid))
        return {'value': name}
    monkeypatch.setattr(R, 'run_function', run)
    monkeypatch.setattr(P, 'enabled', lambda: True)
    async def kind(self, text): return 'read'
    monkeypatch.setattr(P.Prefetch, 'kind', kind)
    async def plan(self, text): return 'job_status', {}
    monkeypatch.setattr(P.Prefetch, 'read_plan', plan)
    return calls


async def ready(text='今の作業はどうなってる？'):
    d = S.Dialogue()
    p = P.Prefetch('u', room_id='r')
    d.prefetch = p
    d.add('user', text)
    p.heard(d)
    await asyncio.sleep(.02)
    return d, p


@pytest.mark.asyncio
async def test_read_consumed_once_through_real_dispatch(reads):
    d, p = await ready()
    item = dict(name='job_status', arguments='{}', call_id='c1')
    out = await S.execute_call(item, 'u', 'r', d, lambda *a, **k: None, 'delegation')
    assert json.loads(out['output']) == {'value':'job_status'}
    assert len(reads) == 1 and p.counts['hit'] == 1
    await S.execute_call(item, 'u', 'r', d, lambda *a, **k: None, 'delegation')
    assert len(reads) == 2
    await p.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['correction', 'cancel', 'other_tool', 'room', 'owner', 'dialogue', 'expired'])
async def test_read_is_never_reused_outside_its_request(reads, change):
    d, p = await ready()
    uid, rid, target = 'u', 'r', d
    if change == 'correction': d.add('user', 'いや、明日の予定のこと')
    if change == 'cancel': d.add('user', 'やっぱり取り消して')
    if change == 'other_tool': p.saw_call(d.turns)
    if change == 'room': rid = 'other-room'
    if change == 'owner': uid = 'other-owner'
    if change == 'dialogue': target = S.Dialogue(); target.turns = d.turns
    if change == 'expired': p.searches[0].started -= P.READ_SECONDS + 1
    assert await p.take_read('job_status', {}, target, uid, rid) is None
    await p.close()


@pytest.mark.asyncio
async def test_correction_during_read_wait_drops_result(reads, monkeypatch):
    event = asyncio.Event()
    async def slow(*a, **kw): await event.wait(); return {'value':'old'}
    monkeypatch.setattr(R, 'run_function', slow)
    d, p = await ready()
    waiting = asyncio.create_task(p.take_read('job_status', {}, d, 'u', 'r'))
    await asyncio.sleep(0)
    d.add('user', 'いや別の作業')
    event.set()
    assert await waiting is None
    await p.close()


@pytest.mark.asyncio
async def test_close_cancels_judge_and_never_starts_late_read(reads, monkeypatch):
    entered = asyncio.Event()
    async def delayed(self, text):
        entered.set()
        await asyncio.sleep(10)
        return 'read'
    monkeypatch.setattr(P.Prefetch, 'kind', delayed)
    d = S.Dialogue(); d.add('user', '今の作業はどうなってる？')
    p = P.Prefetch('u', room_id='r'); p.heard(d)
    await entered.wait(); await p.close()
    assert reads == [] and p.judging.done()
    p.heard(d)
    assert reads == []


@pytest.mark.asyncio
async def test_late_judge_on_corrected_words_does_not_read(reads, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed(self, text):
        entered.set(); await release.wait()
        return 'read' if '取り消し' not in text else 'talk'
    monkeypatch.setattr(P.Prefetch, 'kind', delayed)
    d = S.Dialogue(); d.add('user', '今の作業はどうなってる？')
    p = P.Prefetch('u', room_id='r'); p.heard(d)
    await entered.wait(); d.add('user', '取り消し'); release.set()
    await asyncio.sleep(.02)
    assert reads == []
    await p.close()


@pytest.mark.asyncio
async def test_work_only_reads_operations_and_never_starts_it(reads, monkeypatch):
    async def kind(self, text): return 'work'
    monkeypatch.setattr(P.Prefetch, 'kind', kind)
    d, p = await ready('明日の予約を確定して')
    assert [c[0] for c in reads] == ['list_operations']
    assert await p.take_read('start_work', {'task':'確定'}, d, 'u', 'r') is None
    assert [c[0] for c in reads] == ['list_operations']
    await p.close()


@pytest.mark.asyncio
async def test_parallel_reads_get_one_cache_hit(reads):
    d, p = await ready()
    out = await asyncio.gather(*(p.take_read('job_status', {}, d, 'u', 'r') for _ in range(2)))
    assert sum(x is not None for x in out) == 1
    await p.close()


def test_calendar_and_history_require_equal_effective_arguments():
    p = P.Prefetch('u', room_id='r')
    today = datetime.now(ZoneInfo('Asia/Tokyo')).date()
    e = P.Early('今日の予定', {}, 'get_calendar', {'from':today.isoformat(), 'days':1})
    assert p.same_args(e, 'get_calendar', {'from':today.isoformat()})
    assert not p.same_args(e, 'get_calendar', {})  # backend defaults to 14 days
    assert not p.same_args(e, 'get_calendar', {'from':(today+timedelta(days=1)).isoformat()})
    e = P.Early('新幹線の予約', {}, 'search_records', {'query':'新幹線 予約'})
    e.context = []
    assert p.same_args(e, 'search_records', {'query':'新幹線 予約'})
    assert not p.same_args(e, 'search_records', {'query':'新幹線 取消'})


def test_only_literal_owner_evidence_can_make_a_decision():
    turns = [{'role':'user','text':'じゃあメモリは32GBでお願い'}, {'role':'assistant','text':'予算は20万円でどう？'}]
    assert S.decision_lines([
        {'text':'メモリ32GBにする。','evidence':'メモリは32GBでお願い'},
        {'text':'予算20万円。','evidence':'予算は20万円でどう？'},
        {'text':'購入済み。','evidence':'買った'},
    ], turns) == ['メモリ32GBにする。']


@pytest.mark.asyncio
async def test_after_call_reads_once_and_returns_only_decisions_without_start_notices(monkeypatch):
    started, steps = [], []
    monkeypatch.setattr('app.services.command_job_state.list_owned', lambda *a: [])
    monkeypatch.setattr('app.services.inbox._env', lambda: None)
    class Model:
        def start(self, *args): steps.append(args)
        async def step(self):
            return {'text':json.dumps({'left':[], 'decisions':[{'text':'メモリ32GBにする。','evidence':'32GBでお願い'}]},ensure_ascii=False)}
    monkeypatch.setattr('app.services.api_job_providers.make', lambda *a: Model())
    async def execute(*a): started.append(a)
    monkeypatch.setattr('app.services.command_center.execute', execute)
    out = []
    assert await S.after_call('u','r',[{'role':'user','text':'32GBでお願い'}], 'now', decisions_out=out) == []
    assert out == ['メモリ32GBにする。'] and len(steps) == 1 and started == []
    out.clear()
    await S.after_call('u','r',[{'role':'user','text':'32GBでお願い'}], 'now', decisions_out=out, complete=False)
    assert out == []


def test_summary_retains_early_decisions_after_recent_context_rotates():
    d = S.Dialogue()
    d.add('user','32GBでお願い')
    for i in range(30):
        d.add('assistant',str(i)); d.add('user','はい')
    assert not any('32GB' in t['text'] for t in d.turns)
    assert d.history[0]['text'] == '32GBでお願い'


def test_session_configuration_contains_both_consultation_rules(monkeypatch):
    from app.services import voice_live as L
    monkeypatch.setattr(R, 'catalog', lambda: '')
    monkeypatch.setattr(R, 'remembered', lambda: '')
    monkeypatch.setattr(R, 'tools', lambda: [])
    config = L.session_config()
    assert 'その一点だけ' in config['instructions']
    assert 'その一点だけ' in config['delegation']['responses']['instructions']
    assert config['delegation']['type'] == 'responses'


@pytest.mark.asyncio
async def test_work_guess_does_not_block_later_status_read(reads, monkeypatch):
    async def kind(self, text): return 'read' if 'どう' in text else 'work'
    monkeypatch.setattr(P.Prefetch, 'kind', kind)
    d, p = await ready('今の作業について')
    d.add('user','どうなってる？');p.heard(d)
    await asyncio.sleep(.02)
    assert [c[0] for c in reads] == ['list_operations','job_status']
    assert await p.take_read('job_status', {}, d, 'u','r') == {'value':'job_status'}
    await p.close()


@pytest.mark.asyncio
async def test_call_end_writes_one_decision_message_under_log_and_keeps_stage(monkeypatch):
    from app.services import voice_stage, voice_calls
    from app.services.chat_service import ChatService
    sent = []
    async def write(self, room, user, content, **kwargs):
        sent.append((room,user,content,kwargs))
        return {'id':str(len(sent))}
    monkeypatch.setattr(ChatService, '__init__', lambda self: None)
    monkeypatch.setattr(ChatService, 'send_message', write)
    monkeypatch.setattr(voice_calls, 'begin', lambda *a: None)
    monkeypatch.setattr(voice_calls, 'end', lambda *a: None)
    monkeypatch.setattr(P, 'enabled', lambda: False)
    monkeypatch.setattr(S, 'note', lambda *a, **kw: None)
    class Stage:
        scenes = ['one']
        def __init__(self, *a): pass
        def heard(self, *a): pass
        def close(self): pass
        def summary(self): return '図の記録'
    monkeypatch.setattr(voice_stage, 'Stage', Stage)
    monkeypatch.setattr(voice_stage, 'enabled', lambda: True)
    async def after(*a, decisions_out, **kw):
        decisions_out.append('メモリ32GBにする。')
        return []
    monkeypatch.setattr(S, 'after_call', after)
    events=iter([{'type':'session.input_transcript.delta','delta':'32GBでお願い'}, {'type':'session.closed'}])
    class Socket:
        async def __aenter__(self): return self
        async def __aexit__(self,*a): pass
        async def recv(self): return json.dumps(next(events))
        async def send(self,*a): pass
    import websockets
    monkeypatch.setattr(websockets,'connect',lambda *a,**kw:Socket())
    await S._run('test','u','r','fake',True)
    assert len(sent)==2
    assert sent[0][2].startswith('📞 ダンと通話')
    assert sent[1][2]=='メモリ32GBにする。\n\n図の記録'
    assert datetime.fromisoformat(sent[1][3]['created_at'])-datetime.fromisoformat(sent[0][3]['created_at'])==timedelta(seconds=1)
