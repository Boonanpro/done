import asyncio
import json
from unittest.mock import AsyncMock, patch
import pytest
from app.services.voice_actions import Action, Actions, candidates, choose
from app.services.voice_sideband import Dialogue, execute_call
from app.services.voice_turn_intake import TurnIntake


def setup(text='案内文を半分にして'):
    d = Dialogue(); d.intake = TurnIntake(0)
    d.add('user', text); d.intake.heard(text, 1000)
    r = Actions('u', 'r', d, AsyncMock(), lambda *a, **k: None)
    d.actions = r
    r.snapshot = AsyncMock(return_value=[Action('制作', 'start_work', {'kind': 'make', 'task': text})])
    r.judge = AsyncMock()
    r.judge.choose.return_value = {'available': True, 'answers': {'action': {'choice': '0', 'probabilities': {'0': .99}}}}
    return d, r


@pytest.mark.asyncio
async def test_create_once_and_native_uses_receipt():
    d, r = setup()
    with patch('app.services.voice_responses.run_function', new_callable=AsyncMock, return_value={'accepted': True, 'job_id': 'one'}) as run:
        await r.attempt()
        d.intake.begin('native', 1000)
        out = await execute_call({'name': 'start_work', 'call_id': 'c', 'arguments': '{}'}, 'u', 'r', d, lambda *a, **k: None, 'native')
        assert json.loads(out['output'])['result']['job_id'] == 'one'
        assert run.await_count == 1
        assert d.intake.has_work
        await r.attempt()
        assert run.await_count == 1


@pytest.mark.asyncio
async def test_native_wins_while_jev_is_thinking():
    d, r = setup()
    entered, release = asyncio.Event(), asyncio.Event()
    async def judge(*args):
        entered.set(); await release.wait()
        return {'available': True, 'answers': {'action': {'choice': '0', 'probabilities': {'0': .99}}}}
    r.judge.choose.side_effect = judge
    task = asyncio.create_task(r.attempt()); await entered.wait()
    d.intake.begin('native', 1000)
    assert await r.native_result('native') is None
    release.set(); await task
    assert not r.receipts


@pytest.mark.asyncio
async def test_correction_during_classification_prevents_old_action():
    d, r = setup()
    async def judge(*args):
        d.intake.heard('いや変更しないで', 1100)
        return {'available': True, 'answers': {'action': {'choice': '0', 'probabilities': {'0': .99}}}}
    r.judge.choose.side_effect = judge
    with patch('app.services.voice_responses.run_function', new_callable=AsyncMock) as run:
        await r.attempt()
        run.assert_not_awaited()
    assert not r.receipts


@pytest.mark.asyncio
@pytest.mark.parametrize('answer', [
    {'available': False},
    {'available': True, 'answers': {'action': {'choice': '0', 'probabilities': {'0': .7}}}},
    {'available': True, 'answers': {'action': {'choice': 'reason', 'probabilities': {'reason': 1}}}},
    {'available': True, 'answers': {'action': {'choice': '999', 'probabilities': {'999': 1}}}},
])
async def test_uncertain_or_unknown_choices_preserve_backend(answer):
    d, r = setup(); r.judge.choose.return_value = answer
    await r.attempt()
    assert not r.receipts and not d.intake.owners
    d.intake.begin('native', 1000)
    assert await r.native_result('native') is None


@pytest.mark.asyncio
async def test_native_waits_for_inflight_direct_action_and_does_not_repeat():
    d, r = setup(); entered, release = asyncio.Event(), asyncio.Event()
    async def run(*args):
        entered.set(); await release.wait(); return {'accepted': True}
    with patch('app.services.voice_responses.run_function', side_effect=run) as fn:
        task = asyncio.create_task(r.attempt()); await entered.wait()
        d.intake.begin('native', 1000)
        native = asyncio.create_task(r.native_result('native'))
        await asyncio.sleep(0); assert not native.done()
        release.set(); await task
        assert (await native)['already_executed_for_request']
        assert fn.call_count == 1


@pytest.mark.asyncio
async def test_uncertain_mutation_is_retained_and_never_retried():
    d, r = setup()
    with patch('app.services.voice_responses.run_function', new_callable=AsyncMock, side_effect=OSError('uncertain')) as run:
        await r.attempt()
        d.intake.begin('native', 1000)
        result = await r.native_result('native')
        assert result['result']['error'] == 'OSError'
        await r.attempt(); assert run.await_count == 1


@pytest.mark.asyncio
async def test_new_request_is_not_blocked_by_previous_receipt():
    d, r = setup()
    with patch('app.services.voice_responses.run_function', new_callable=AsyncMock, return_value={'accepted': True}):
        await r.attempt()
        d.intake.heard('無料にして', 4000); r.heard(3000, 4000)
        d.intake.begin('new', 4000)
        assert await r.native_result('new') is None


def test_observed_targets_and_original_words_only():
    jobs = [{'id': 'first', 'state': 'running', 'task': '案内文'}, {'id': 'second', 'state': 'running', 'task': '動画'}]
    screen = {'page_id': 'page', 'controls': [
        {'id': 'nav', 'name': '次の候補', 'fingerprint': 'fp', 'risk': 'navigate'},
        {'id': 'send', 'name': '送信', 'fingerprint': 'fp2', 'risk': 'confirm'},
        {'id': 'edit', 'name': '金額', 'fingerprint': 'fp3', 'risk': 'edit'}]}
    items = candidates('案内文の参加費を無料にして', jobs, screen)
    updates = [a for a in items if a.name == 'steer_job' and a.args['kind'] == 'update']
    assert {a.args['job_id'] for a in updates} == {'first', 'second'}
    assert all(a.args['instruction'] == '案内文の参加費を無料にして' for a in updates)
    clicks = [a for a in items if a.name == 'operate_screen']
    assert len(clicks) == 1 and clicks[0].args == {'op': 'click', 'target': 'nav', 'page_id': 'page', 'fingerprint': 'fp'}


def test_truncated_job_list_never_selects_a_partial_set():
    items = candidates('それを止めて', [{'id': str(i), 'state': 'running'} for i in range(20)])
    assert not any(a.name == 'steer_job' for a in items)


def test_known_foreign_run_retains_project_and_run_ids():
    items = candidates('開発室を止めて', observed=[{'project': {'id': 'p', 'title': '開発室'}, 'run': {'id': 'run', 'state': 'running'}}])
    assert next(a for a in items if a.name == 'stop_run').args == {'project_id': 'p', 'run_id': 'run'}


@pytest.mark.asyncio
async def test_direct_screen_action_uses_normal_validation():
    d, r = setup('次の候補を開いて')
    action = Action('次の候補', 'operate_screen', {'op': 'click', 'page_id': 'p', 'target': 't', 'fingerprint': 'old'})
    r.snapshot.return_value = [action]
    with patch('app.services.voice_responses.run_function', new_callable=AsyncMock, return_value={'ok': False, 'error': '画面が変わりました'}) as run:
        await r.attempt()
        assert run.await_args.args[:2] == ('operate_screen', action.args)
        assert (await r.receipts[1])['ok'] is False


@pytest.mark.asyncio
async def test_new_words_while_executing_suppress_old_spoken_result():
    d, r = setup()
    async def run(*args):
        d.intake.heard('やっぱりやめて', 2000)
        return {'accepted': True}
    with patch('app.services.voice_responses.run_function', side_effect=run):
        await r.attempt()
    r.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_late_tail_cannot_reexecute_whole_previous_request():
    d, r = setup()
    with patch('app.services.voice_responses.run_function', new_callable=AsyncMock, return_value={'accepted': True}) as run:
        await r.attempt()
        d.intake.heard('お願いします', 1200)
        r.heard(1100, 1200)
        await r.attempt()
        assert run.await_count == 1


@pytest.mark.asyncio
async def test_separate_utterance_can_route_after_previous_action():
    d, r = setup(); r.heard(0, 1000)
    with patch('app.services.voice_responses.run_function', new_callable=AsyncMock, return_value={'accepted': True}) as run:
        await r.attempt()
        d.intake.heard('明日の予定を教えて', 5000)
        r.heard(3000, 5000)
        r.snapshot.return_value = [Action('明日の予定', 'get_calendar', {'days': 1, 'from': '2026-11-02'})]
        await r.attempt()
        assert run.await_count == 2
        r.snapshot.assert_awaited_with('明日の予定を教えて')


@pytest.mark.asyncio
async def test_direct_route_does_not_claim_on_call_close():
    d, r = setup()
    async def judge(*args):
        d.intake.close()
        return {'available': True, 'answers': {'action': {'choice': '0', 'probabilities': {'0': .99}}}}
    r.judge.choose.side_effect = judge
    await r.attempt()
    assert not r.receipts


@pytest.mark.asyncio
async def test_large_result_requests_summary_without_repeating_operation():
    d, r = setup('資料一覧を教えて')
    with patch('app.services.voice_responses.run_function', new_callable=AsyncMock, return_value={'files': ['a'*11000]}) as run:
        await r.attempt()
        assert r.send.await_args.args[0]['type'] == 'response.create'
        d.intake.begin('summary', 1000)
        assert (await r.native_result('summary'))['result']['files']
        assert run.await_count == 1
