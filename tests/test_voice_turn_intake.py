import asyncio
import json
import pytest
from app.services.voice_turn_intake import TurnIntake, dispatch_missing
from app.services import voice_sideband as S


def test_automatic_and_fallback_share_one_admission():
    i = TurnIntake()
    i.heard('参加費を無料に変えて', 1000, now=1)
    assert i.reserve(3) == 1
    i.begin('native', 1100)
    i.begin('fallback', 1100)
    assert i.reject('native') is None
    assert i.reject('fallback') == 'already_admitted'
    assert i.reserve(5) is None


def test_late_native_response_cannot_execute_a_newer_correction():
    i = TurnIntake()
    i.heard('無料に', 1000, now=1)
    i.heard('いや五百円のままで', 2000, now=2)
    i.begin('old', 1100)
    assert i.reject('old') == 'newer_or_unassociated_speech'
    i.finish('old')
    assert i.reserve(4) == 2
    i.begin('new')
    assert i.reject('new') is None


def test_new_words_are_not_consumed_by_late_forced_acknowledgement():
    i = TurnIntake()
    i.heard('無料にして', 1000, now=1)
    assert i.reserve(3) == 1
    i.heard('やっぱりそのままで', 2000, now=4)
    i.begin('late')
    assert i.reject('late') == 'newer_or_unassociated_speech'
    i.finish('late')
    assert i.reserve(6) == 2


def test_unknown_native_timing_is_not_assumed_to_cover_latest_words():
    i = TurnIntake()
    i.heard('送らないで', None, now=1)
    i.begin('unknown')
    assert i.reject('unknown') == 'newer_or_unassociated_speech'
    i.finish('unknown')
    assert i.reserve(3) == 1


def test_new_request_after_completion_is_allowed():
    i = TurnIntake()
    i.heard('短くして', 1000, now=1)
    i.begin('first', 1100)
    assert i.reject('first') is None
    i.finish('first')
    i.heard('無料にして', 5000, now=5)
    i.begin('second', 5100)
    assert i.reject('second') is None


@pytest.mark.asyncio
async def test_uncertain_send_is_never_retried():
    i = TurnIntake(0)
    i.has_work = True
    i.heard('無料にして', 1000)
    sends = []
    async def send(event):
        sends.append(event)
        raise OSError('uncertain')
    await dispatch_missing(i, send, lambda *a, **k: None)
    assert len(sends) == 1
    assert i.reserve() is None


@pytest.mark.asyncio
async def test_native_and_fallback_cannot_edit_twice(monkeypatch, tmp_path):
    memo = tmp_path / 'memo.txt'
    memo.write_text('参加費500円')
    writes = []
    async def run(name, args, *a, **kw):
        writes.append(args)
        memo.write_text(args['instruction'])
        return {'accepted': True}
    monkeypatch.setattr('app.services.voice_responses.run_function', run)
    d = S.Dialogue(); d.intake = TurnIntake(0)
    d.intake.has_work = True
    d.intake.heard('参加費を無料に変えて', 1000)
    d.intake.begin('native', 1100); d.intake.begin('fallback', 1100)
    item = {'name': 'steer_job', 'call_id': 'c', 'arguments': json.dumps({'job_id': 'one', 'instruction': '参加費無料'})}
    results = await asyncio.gather(*(S.execute_call(dict(item, call_id=key), 'u', 'r', d, lambda *a, **kw: None, key) for key in ('native', 'fallback')))
    assert memo.read_text() == '参加費無料'
    assert len(writes) == 1
    assert sum(json.loads(r['output']).get('accepted') is True for r in results) == 1


@pytest.mark.asyncio
async def test_correction_during_settling_prevents_old_mutation(monkeypatch):
    calls = []
    async def run(*a, **kw): calls.append(a); return {}
    monkeypatch.setattr('app.services.voice_responses.run_function', run)
    d = S.Dialogue(); d.intake = TurnIntake(.05)
    d.intake.has_work = True
    d.intake.heard('送って', 1000); d.intake.begin('old', 1100)
    task = asyncio.create_task(S.execute_call({'name': 'send_message_on_stage', 'call_id': 'c'}, 'u', 'r', d, lambda *a, **kw: None, 'old'))
    await asyncio.sleep(.01)
    d.intake.heard('いや送らないで', 2000)
    out = await task
    assert not calls
    assert json.loads(out['output'])['accepted'] is False


@pytest.mark.asyncio
async def test_attention_does_not_discard_original_edit(monkeypatch):
    calls = []
    async def run(*a, **kw): calls.append(a); return {'accepted': True}
    monkeypatch.setattr('app.services.voice_responses.run_function', run)
    d = S.Dialogue(); d.intake = TurnIntake(0)
    d.intake.has_work = True
    d.intake.heard('短くして', 1000); d.intake.begin('first', 1100)
    d.intake.heard('聞いて', 2000); d.intake.heard('る？', 2200)
    out = await S.execute_call({'name': 'start_work', 'call_id': 'c'}, 'u', 'r', d, lambda *a, **kw: None, 'first')
    assert json.loads(out['output'])['accepted'] is True
    assert len(calls) == 1
    d.intake.finish('first')
    assert d.intake.reserve() is None
    d.intake.heard('無料に変えて', 3000)
    assert d.intake.reject('first') == 'newer_or_unassociated_speech'


@pytest.mark.asyncio
async def test_stale_status_read_does_not_reserve_mutation_owner(monkeypatch):
    async def run(*a, **kw): return {'work_status': []}
    monkeypatch.setattr('app.services.voice_responses.run_function', run)
    d = S.Dialogue(); d.intake = TurnIntake(0)
    d.intake.has_work = True
    d.intake.heard('様子は', 1000); d.intake.begin('old', 1100)
    d.intake.heard('無料にして', 2000)
    out = await S.execute_call({'name': 'job_status', 'call_id': 'c'}, 'u', 'r', d, lambda *a, **kw: None, 'old')
    assert 'work_status' in json.loads(out['output'])
    assert not d.intake.owners


def test_forced_event_echo_keeps_reserved_words_despite_late_offset():
    i = TurnIntake()
    i.heard('送って', 1000, now=1)
    assert i.reserve(3) == 1
    i.reserved_event = 'event1'
    i.heard('いや送らないで', 2000, now=4)
    i.begin('forced', 2200, 'event1')
    assert i.delegations['forced'] == 1
    assert i.reject('forced') == 'newer_or_unassociated_speech'


def test_attention_native_cannot_repeat_an_admitted_edit():
    i = TurnIntake()
    i.heard('短くして', 1000, now=1)
    i.begin('first', 1100)
    assert i.reject('first') is None
    i.heard('聞いてる？', 2000, now=2)
    i.begin('attention', 2100)
    assert i.reject('attention') == 'already_admitted'


@pytest.mark.asyncio
async def test_no_extra_backend_before_a_job_was_accepted():
    i = TurnIntake(0)
    i.heard('こんにちは', 1000)
    sent = []
    async def send(event): sent.append(event)
    task = asyncio.create_task(dispatch_missing(i, send, lambda *a, **kw: None))
    await asyncio.sleep(.25)
    i.close()
    await task
    assert not sent


@pytest.mark.asyncio
async def test_only_confirmed_work_enables_fallback(monkeypatch):
    async def run(*a, **kw): return {'accepted': False}
    monkeypatch.setattr('app.services.voice_responses.run_function', run)
    d = S.Dialogue(); d.intake = TurnIntake(0)
    d.intake.heard('短くして', 1000); d.intake.begin('first', 1100)
    item = {'name': 'start_work', 'call_id': 'c'}
    await S.execute_call(item, 'u', 'r', d, lambda *a, **kw: None, 'first')
    assert not d.intake.has_work
    async def success(*a, **kw): return {'accepted': True, 'job_id': 'one'}
    monkeypatch.setattr('app.services.voice_responses.run_function', success)
    await S.execute_call(item, 'u', 'r', d, lambda *a, **kw: None, 'first')
    assert d.intake.has_work and d.intake.owners == {1: 'first'}


@pytest.mark.asyncio
async def test_first_work_hint_dispatches_latest_words_only_once():
    i = TurnIntake(0)
    i.heard('案内文を短くして', 1000)
    i.work_hint = True
    i.heard('いや、まだ変更しないで', 2000)
    sent = []
    async def send(event):
        sent.append(event)
        i.begin('fallback', client_event_id=event['event_id'])
        i.close()
    await dispatch_missing(i, send, lambda *a, **kw: None)
    assert len(sent) == 1
    assert i.delegations['fallback'] == 2
    assert not i.has_work  # reasoning is not execution or approval


@pytest.mark.asyncio
async def test_first_native_and_fallback_do_not_start_two_jobs(monkeypatch):
    calls = []
    async def run(*a, **kw):
        calls.append(a)
        return {'accepted': True, 'job_id': 'one'}
    monkeypatch.setattr('app.services.voice_responses.run_function', run)
    d = S.Dialogue(); d.intake = TurnIntake(0)
    d.intake.work_hint = True
    d.intake.heard('案内文を短くして', 1000)
    d.intake.begin('native', 1100); d.intake.begin('fallback', 1100)
    item = {'name': 'start_work', 'arguments': '{}'}
    out = await asyncio.gather(*(S.execute_call(dict(item, call_id=key), 'u', 'r', d,
        lambda *a, **kw: None, key) for key in ('native', 'fallback')))
    assert len(calls) == 1
    assert sum(json.loads(r['output']).get('accepted') is True for r in out) == 1


@pytest.mark.asyncio
async def test_prefetch_work_hint_does_not_accept_stale_judgement(monkeypatch):
    from app.services.voice_prefetch import Prefetch
    d = S.Dialogue(); d.intake = TurnIntake(0)
    d.add('user', '案内文を短くして')
    p = Prefetch('u', room_id='r')
    monkeypatch.setattr(p, 'heard', lambda *a: None)
    monkeypatch.setattr(p, 'start_read', lambda *a: None)
    async def work(text): return 'work'
    monkeypatch.setattr(p, 'kind', work)
    turn = d.turns[-1]
    await p._judge_and_search(d, turn['text'], turn)
    assert d.intake.work_hint and not d.intake.has_work
    d.intake.work_hint = False
    async def stale(text):
        d.add('user', 'いや、変更しないで')
        return 'work'
    monkeypatch.setattr(p, 'kind', stale)
    await p._judge_and_search(d, turn['text'], turn)
    assert not d.intake.work_hint
