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
async def test_cancelled_backend_does_not_run_a_fallback_read(reads, monkeypatch):
    async def slow(*a, **kw):
        reads.append(a[0]); await asyncio.Event().wait()
    monkeypatch.setattr(R, 'run_function', slow)
    d, p = await ready()
    task = asyncio.create_task(S.execute_call({'name':'job_status','arguments':'{}'},'u','r',d,lambda *a,**kw:None,'x'))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    await p.close()
    assert reads == ['job_status']


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
    e.args = {'query':'あれ'}
    e.context = [{'role':'user','text':'新幹線'}, {'role':'user','text':'カメラ'}]
    assert not p.same_args(e, 'search_records', {'query':'あれ'}, e.context + [{'role':'assistant','text':'はい'}])


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


@pytest.mark.asyncio
@pytest.mark.parametrize('summary_fails', [False, True])
async def test_merged_stage_survives_call_end_and_decision_extraction_failure(monkeypatch, tmp_path, summary_fails):
    """Real merged Stage + real sideband close; only model/socket/storage boundaries are fixtures."""
    from app.services import voice_stage as V, voice_calls
    from app.services.chat_service import ChatService
    import websockets
    sent, notes = [], []
    monkeypatch.setattr(V, 'ROOT', tmp_path)
    previous = V.Stage('integration-room', 'previous-call', S.Dialogue(), lambda *a, **kw: None)
    for _ in range(7): previous._apply('古い画面', 'root = Stat("前の通話", 1)')
    previous.close()
    async def draw(*a):
        return {'action':'replace', 'caption':'決まった仕様', 'program':'root = Flow([{id: "a", label: "きっぷ", icon: "ticket"}, {id: "b", label: "改札", icon: "gate"}])'}, {}
    monkeypatch.setattr(V, 'ask_model', draw)
    monkeypatch.setattr(V, 'enabled', lambda: True)
    monkeypatch.setattr(P, 'enabled', lambda: False)
    monkeypatch.setattr(voice_calls, 'begin', lambda *a: None)
    monkeypatch.setattr(voice_calls, 'end', lambda *a: None)
    monkeypatch.setattr(S, 'note', lambda *a, **kw: notes.append((a,kw)))
    async def idle(*a): await asyncio.Event().wait()
    monkeypatch.setattr(S, 'job_feed', idle)
    monkeypatch.setattr(S, 'chat_feed', idle)
    async def write(self, room, user, content, **kwargs):
        assert (room,user) == ('integration-room','test-user')
        sent.append((content,kwargs)); return {'id':str(len(sent))}
    monkeypatch.setattr(ChatService, '__init__', lambda self: None)
    monkeypatch.setattr(ChatService, 'send_message', write)
    async def after(*a, decisions_out, **kw):
        if summary_fails: raise RuntimeError('fixture model unavailable')
        decisions_out.append('メモリ32GBにする。'); return []
    monkeypatch.setattr(S, 'after_call', after)
    class Socket:
        count = 0
        async def __aenter__(self): return self
        async def __aexit__(self,*a): pass
        async def send(self,*a): pass
        async def recv(self):
            self.count += 1
            if self.count == 1: return json.dumps({'type':'session.input_transcript.delta','delta':'32GBでお願い'})
            stage = V.for_room('integration-room')
            assert stage.session_id == 'integration-call'
            await stage.show('今の決定を図にして')
            assert V.read_state('integration-room')['version'] == 8
            return json.dumps({'type':'session.closed'})
    monkeypatch.setattr(websockets, 'connect', lambda *a, **kw: Socket())
    await S._run('integration-call','test-user','integration-room','fixture',True)
    assert len(sent) == 2 and sent[0][0].startswith('📞 ダンと通話')
    assert sent[1][0].count('```openui-lang') == 1
    assert ('メモリ32GBにする。' in sent[1][0]) is not summary_fails
    assert 'icon: "doc"' in sent[1][0] and 'icon: "check"' in sent[1][0]
    assert '前の通話' not in sent[1][0]
    assert datetime.fromisoformat(sent[1][1]['created_at']) - datetime.fromisoformat(sent[0][1]['created_at']) == timedelta(seconds=1)
    state = V.read_state('integration-room')
    assert not state['active'] and state['version'] == 8 and V.for_room('integration-room') is None

@pytest.mark.asyncio
async def test_combined_classification_selects_read_in_one_request():
    class Judge:
        calls = 0
        async def choose(self, state, questions):
            self.calls += 1
            assert set(questions) == {'kind','read'}
            return {'available':True,'answers':{'kind':{'choice':'read','probabilities':{'read':1}},
                'read':{'choice':'job_status','probabilities':{'job_status':1}}}}
    p = P.Prefetch('u',room_id='r');p.judge=Judge()
    assert await p.kind('今の作業はどうなってる') == 'read'
    assert await p.read_plan('今の作業はどうなってる') == ('job_status',{})
    assert p.judge.calls == 1


@pytest.mark.asyncio
async def test_long_phrase_does_not_repeat_expired_speculative_read(reads):
    d,p=await ready()
    p.searches[0].started -= P.READ_SECONDS+1
    d.add('user','教えてください');p.heard(d)
    await asyncio.sleep(.02)
    assert len(reads) == 1
    assert await p.take_read('job_status',{},d,'u','r') is None
    await p.close()


@pytest.mark.asyncio
async def test_slow_handoff_cannot_hold_summary_or_drop_later_requests(monkeypatch,tmp_path):
    from app.services import voice_stage as V
    from app.services.chat_service import ChatService
    from datetime import timezone
    from app.services import command_center, command_job_state, api_job_providers, inbox
    monkeypatch.setattr(S,'FOLLOWUP_ROOT',tmp_path/'handoff')
    monkeypatch.setattr(V,'ROOT',tmp_path/'stage')
    monkeypatch.setattr(command_job_state,'list_owned',lambda *a:[])
    monkeypatch.setattr(inbox,'_env',lambda:None)
    entered, release, model_release = asyncio.Event(),asyncio.Event(),asyncio.Event()
    tasks, saved = [],[]
    class Model:
        def start(self,system,tools,messages):
            assert '最初の依頼' in messages[0] and '最後は取り消し' in messages[0]
            assert len(messages[0]) > 65000
        async def step(self):
            await model_release.wait()
            return {'text':json.dumps({'left':[{'task':f'資料{i}を作る'} for i in range(5)],
                'decisions':[{'text':'メモリ32GBにする。','evidence':'32GBでお願い'}]})}
    monkeypatch.setattr(api_job_providers,'make',lambda *a:Model())
    async def execute(spec,*a):
        tasks.append(spec)
        if len(tasks)==1:
            entered.set(); await release.wait()
        if len(tasks)==2: raise RuntimeError('one enqueue failed')
        return {'accepted':True,'id':str(len(tasks))}
    monkeypatch.setattr(command_center,'execute',execute)
    monkeypatch.setattr(ChatService,'__init__',lambda self:None)
    async def write(self,*a,**kw): saved.append((a,kw));return {'id':'fixture'}
    monkeypatch.setattr(ChatService,'send_message',write)
    d=S.Dialogue();d.add('user','最初の依頼。32GBでお願い')
    for i in range(110):
        d.add('assistant','長い相談の内容。'*80);d.add('user','続けて。')
    d.add('user','最後は取り消し。')
    assert d.history_complete and d.history_chars>65000
    stage=V.Stage('r','s',d,lambda *a,**kw:None)
    stage._apply('図','root = Stat("メモリ", 32, "GB")');stage.close()
    finish=asyncio.create_task(S.finish_call('u','r',d,datetime.now(timezone.utc),True,stage,lambda *a,**kw:None))
    # Model delay and enqueue delay are independent; neither is wrapped in 30s wait_for.
    await asyncio.sleep(.02);assert not saved and not tasks
    model_release.set();await entered.wait()
    assert len(saved)==1 and 'メモリ32GB' in saved[0][0][2] and '```openui-lang' in saved[0][0][2]
    assert len(tasks)==1
    release.set();await finish
    # everything left by one call goes as ONE piece of work (2026-10-27: three jobs queued on the phone)
    assert len(tasks)==1 and len(saved)==1
    assert all(f'{i+1}. 資料{i}を作る' in tasks[0]['task'] for i in range(5))
    paths=list((tmp_path/'handoff').rglob('*.json'));assert len(paths)==1
    data=json.loads(paths[0].read_text());assert len(data['requests'])==5 and len(data['receipts'])==1
    assert data['turns'][0]['text'].startswith('最初の依頼') and '最後は取り消し' in data['turns'][-1]['text']
    assert paths[0].stat().st_mode & 0o777 == 0o600
    assert str(paths[0]) in tasks[0]['task'] and len(tasks[0]['task'])<=2800
    assert '同じ条件への有効な承認が確認できたら' in tasks[0]['task']
    assert '候補選択・予算指定だけから承認を作らない' in tasks[0]['task']

@pytest.mark.asyncio
async def test_socket_cancellation_keeps_post_call_owner_alive(monkeypatch):
    from app.services import voice_calls,voice_stage
    import websockets
    entered,release,finished=asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def finish(*a): entered.set();await release.wait();finished.set()
    monkeypatch.setattr(S,'finish_call',finish)
    monkeypatch.setattr(P,'enabled',lambda:False)
    monkeypatch.setattr(voice_stage,'enabled',lambda:False)
    monkeypatch.setattr(voice_calls,'begin',lambda *a:None)
    monkeypatch.setattr(voice_calls,'end',lambda *a:None)
    monkeypatch.setattr(S,'note',lambda *a,**kw:None)
    async def nothing(*a,**kw): pass
    monkeypatch.setattr(S,'call_log',nothing)
    async def idle(*a):await asyncio.Event().wait()
    monkeypatch.setattr(S,'job_feed',idle);monkeypatch.setattr(S,'chat_feed',idle)
    class Socket:
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        async def recv(self):return '{"type":"session.closed"}'
        async def send(self,*a):pass
    monkeypatch.setattr(websockets,'connect',lambda *a,**kw:Socket())
    task=asyncio.create_task(S._run('fixture','u','r','fixture',True))
    await entered.wait();task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert any(not t.done() for t in S._after_tasks)
    release.set();await asyncio.wait_for(finished.wait(),1)
    await asyncio.sleep(0)
    assert not S._after_tasks

@pytest.mark.asyncio
async def test_bad_extraction_preserves_original_and_never_manufactures_approval(monkeypatch,tmp_path):
    from app.services import command_center,command_job_state,api_job_providers,inbox
    monkeypatch.setattr(S,'FOLLOWUP_ROOT',tmp_path)
    monkeypatch.setattr(command_job_state,'list_owned',lambda *a:[])
    monkeypatch.setattr(inbox,'_env',lambda:None)
    class Model:
        def start(self,*a):pass
        async def step(self):return {'text':'{"approved":true}'}
    monkeypatch.setattr(api_job_providers,'make',lambda *a:Model())
    calls=[]
    async def execute(spec,*a):calls.append(spec);return {'accepted':True}
    monkeypatch.setattr(command_center,'execute',execute)
    await S.after_call('u','r',[{'role':'user','text':'予算は20万円まで。まだ買わないで。'}],'now')
    assert len(calls)==1 and calls[0]['action']=='work'
    assert set(calls[0])=={'action','task','engine'}
    assert '未完了の依頼があれば' in calls[0]['task']
    state=json.loads(next(tmp_path.rglob('*.json')).read_text())
    assert state['turns'][0]['text'].endswith('まだ買わないで。')
    assert state['requests_source']=='automatic extraction, not authorization'


@pytest.mark.asyncio
async def test_left_over_goes_to_the_calls_running_work(monkeypatch,tmp_path):
    """「今どういう状況」 about a running transfer must not start a second transfer job (2026-10-27)."""
    from app.services import command_center, command_job_state, api_job_providers, inbox
    monkeypatch.setattr(S,'FOLLOWUP_ROOT',tmp_path/'handoff')
    began='2026-10-27T08:19:00+00:00'
    monkeypatch.setattr(command_job_state,'list_owned',lambda *a:[{'id':'j1','task':'振込の準備','state':'running','created_at':'2026-10-27T08:20:09+00:00'}])
    monkeypatch.setattr(inbox,'_env',lambda:None)
    class Model:
        def start(self,*a): pass
        async def step(self): return {'text':json.dumps({'left':[{'task':'振込の状況を確認して報告する'}],'decisions':[]})}
    monkeypatch.setattr(api_job_providers,'make',lambda *a:Model())
    updates, created = [], []
    monkeypatch.setattr(command_job_state,'control',lambda job,user,room,action,text='':updates.append((job,action,text)))
    async def execute(spec,*a): created.append(spec); return {'accepted':True}
    monkeypatch.setattr(command_center,'execute',execute)
    left = await S.after_call('u','r',[{'role':'user','text':'今どういう状況'}],began)
    assert left and not created
    assert updates[0][0]=='j1' and updates[0][1]=='update' and '振込の状況' in updates[0][2]
