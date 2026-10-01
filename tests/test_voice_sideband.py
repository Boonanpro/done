import asyncio
import json

import pytest

from app.services import voice_sideband as S


def test_only_metadata_is_kept_never_words_or_audio():
    kept = S.summary({'type': 'session.delegation.created', 'delegation': {'id': 'dlg_1', 'target': 'client'}, 'request': '郵便番号を確認して', 'audio': 'AAAA'})
    assert kept['event'] == 'session.delegation.created' and kept['delegation_id'] == 'dlg_1' and kept['request_chars'] == 9
    kept = S.summary({'type': 'session.input_transcript.delta', 'delta': 'カード番号は', 'role': 'user'})
    assert 'カード' not in json.dumps(kept, ensure_ascii=False) and kept['delta_chars'] == 6
    kept = S.summary({'type': 'error', 'error': {'type': 'invalid_request_error', 'code': 'x', 'message': 'bad event'}})
    assert kept['error']['message'] == 'bad event'   # why a call ended is worth keeping


def test_switch_and_missing_key_do_nothing(monkeypatch):
    monkeypatch.setenv('DAN_VOICE_SIDEBAND', '0')
    assert S.attach('sess_1', 'u', 'room', 'key', own=True) is False
    monkeypatch.delenv('DAN_VOICE_SIDEBAND')
    assert S.attach('sess_1', 'u', 'room', '', own=True) is False and not S._tasks


def test_consecutive_deltas_of_one_speaker_are_one_turn():
    d = S.Dialogue()
    for role, text in (('user', '郵便'), ('user', '番号は?'), ('assistant', '確認'), ('assistant', 'します'), ('user', 'まだ?')):
        d.add(role, text)
    assert d.recent() == [{'role': 'user', 'text': '郵便番号は?'}, {'role': 'assistant', 'text': '確認します'}, {'role': 'user', 'text': 'まだ?'}]


def test_long_answers_are_cut_at_sentence_ends_under_the_append_limit():
    parts = list(S.chunks('あ'*250+'。'+'い'*250+'。'))
    assert all(len(p) <= S.CHUNK for p in parts) and parts[0].endswith('。') and ''.join(parts) == 'あ'*250+'。'+'い'*250+'。'


@pytest.mark.asyncio
async def test_job_feed_speaks_results_at_once_and_pushes_nothing_else(monkeypatch):
    """Results are spoken the moment they appear. The running work's state is never pushed: the backend reads it with
    job_status when the owner asks (pushing it made the speech model say 「もう少し待って」 unprompted)."""
    sent, jobs = [], []
    async def send(event): sent.append(event)
    monkeypatch.setattr('app.services.command_job_state.list_owned', lambda u, r: [dict(j) for j in jobs])
    monkeypatch.setattr(S, 'FEED_SECONDS', .01)
    feed = asyncio.create_task(S.job_feed(send, 'u', 'room', lambda *a, **k: None, '2026-09-22T03:00:00+00:00'))
    try:
        jobs.append({'id': 'job-1', 'task': '今回のユーザー発言（原文）:\n24日の新幹線を取って\n参考の直前会話: ...', 'state': 'running', 'seq': 2, 'created_at': '2026-09-22T03:01:00+00:00',
                     'events': [{'seq': 1, 'kind': 'progress', 'text': '依頼内容を確認しています'}, {'seq': 2, 'kind': 'tool', 'text': 'browser:open_target'}],
                     'current_tool': {'name': 'browser', 'action': 'open_target'}, 'last_observation': {'text': 'URL: https://smart-ex.jp/x\nタイトル: スマートEX'}})
        await asyncio.sleep(.05)
        assert sent == []   # a running job pushes nothing: its state is read on demand (job_status)
        jobs[0].update(seq=3, state='completed', events=jobs[0]['events']+[{'seq': 3, 'kind': 'result', 'text': 'のぞみ2号を予約可能です'}])
        await asyncio.sleep(.05)
        assert [e['type'] for e in sent] == ['session.commentary.append'] and 'のぞみ2号' in sent[0]['content']
    finally:
        feed.cancel()


@pytest.mark.asyncio
async def test_job_feed_ignores_work_finished_before_the_call(monkeypatch):
    sent = []
    async def send(event): sent.append(event)
    old = {'id': 'job-0', 'task': '昔の作業', 'state': 'completed', 'seq': 1, 'created_at': '2026-09-21T00:00:00+00:00', 'events': [{'seq': 1, 'kind': 'result', 'text': '済み'}]}
    monkeypatch.setattr('app.services.command_job_state.list_owned', lambda u, r: [old])
    monkeypatch.setattr(S, 'FEED_SECONDS', .01)
    feed = asyncio.create_task(S.job_feed(send, 'u', 'room', lambda *a, **k: None, '2026-09-22T03:00:00+00:00'))
    await asyncio.sleep(.05); feed.cancel()
    assert sent == []


@pytest.mark.asyncio
async def test_parallel_function_calls_are_answered_together_with_one_response_create(monkeypatch):
    sent, pending = [], {}
    async def send(event): sent.append(event)
    async def fake_run(name, args, user_id, room_id, dialogue, **_): return {'ok': name}
    monkeypatch.setattr('app.services.voice_responses.run_function', fake_run)
    d = S.Dialogue(); rec = lambda *a, **k: None
    for call_id, name in (('c1', 'get_calendar'), ('c2', 'get_saved_information')):
        await S.handle_response_event(send, 's', 'u', 'r', {'type': 'response.event', 'delegation_id': 'd1', 'event': {'type': 'response.output_item.done', 'item': {'type': 'function_call', 'call_id': call_id, 'name': name, 'arguments': '{}'}}}, d, rec, pending)
    assert sent == []   # nothing goes back until the response is complete
    await S.handle_response_event(send, 's', 'u', 'r', {'type': 'response.event', 'delegation_id': 'd1', 'event': {'type': 'response.completed'}}, d, rec, pending)
    assert [e['type'] for e in sent] == ['response.item.create', 'response.item.create', 'response.create']
    assert {e['item']['call_id'] for e in sent[:2]} == {'c1', 'c2'} and pending == {}


@pytest.mark.asyncio
async def test_end_call_leaves_the_hang_up_to_the_phone_and_closes_later_only_as_a_fallback(monkeypatch):
    """The backend chooses end_call; the phone hangs up 4 s later so Dan can finish speaking. The server must not close
    at once (that stopped Dan mid-word, 2026-10-01); it closes after HANGUP_FALLBACK_S for clients that don't."""
    monkeypatch.setattr(S, 'HANGUP_FALLBACK_S', 0.05)
    sent, pending = [], {}
    async def send(event): sent.append(event)
    async def fake_run(name, args, user_id, room_id, dialogue, **_): return {'ok': True}
    monkeypatch.setattr('app.services.voice_responses.run_function', fake_run)
    d = S.Dialogue(); rec = lambda *a, **k: None
    await S.handle_response_event(send, 's', 'u', 'r', {'type': 'response.event', 'delegation_id': 'd1', 'event': {'type': 'response.output_item.done', 'item': {'type': 'function_call', 'call_id': 'c1', 'name': 'end_call', 'arguments': '{}'}}}, d, rec, pending)
    await S.handle_response_event(send, 's', 'u', 'r', {'type': 'response.event', 'delegation_id': 'd1', 'event': {'type': 'response.completed'}}, d, rec, pending)
    assert sent == []
    await asyncio.sleep(0.1)
    assert [e['type'] for e in sent] == ['session.close']


@pytest.mark.asyncio
async def test_what_the_call_left_undone_becomes_work_reported_in_the_room(monkeypatch):
    """Hung up before Dan answered or handed it on: the call is read once and each thing left is worked on afterwards."""
    started = []
    async def execute(spec, room_id, user_id): started.append((room_id, spec['task'])); return {'accepted': True}
    monkeypatch.setattr('app.services.command_center.execute', execute)
    monkeypatch.setattr('app.services.command_job_state.list_owned', lambda u, r: [])
    class Model:
        def start(self, *a): self.seen = a
        async def step(self): return {'text': '{"left": [{"task": "来週金曜の朝、新大阪→品川の新幹線の空きを確認する"}]}'}
    monkeypatch.setattr('app.services.api_job_providers.make', lambda model: Model())
    monkeypatch.setattr('app.services.inbox._env', lambda: None)
    turns = [{'role': 'user', 'text': '来週の新幹線見といて。あ、着いた、切るわ'}, {'role': 'assistant', 'text': 'わかった、確認し'}]
    assert await S.after_call('u', 'room-1', turns, '2026-10-01T00:00:00') == ['来週金曜の朝、新大阪→品川の新幹線の空きを確認する']
    assert started[0][0] == 'room-1' and 'チャットに文章で報告' in started[0][1]
    started.clear()
    assert await S.after_call('u', 'room-1', [{'role': 'assistant', 'text': 'もしもし'}], '2026-10-01T00:00:00') == [] and not started
