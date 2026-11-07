"""The plain call hands its lookups to the background (voice_lookup): the delegation is answered at once and the facts
reach the call as commentary. 2026-11-03 19:15: one delegation stayed open for 44 s and the owner's correction waited 25 s."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services import voice_lookup, voice_responses
from app.services.voice_sideband import Dialogue


def call_item(name, arguments, call_id):
    return SimpleNamespace(type='function_call', name=name, arguments=json.dumps(arguments, ensure_ascii=False), call_id=call_id)


def response(output, text=''):
    return SimpleNamespace(id='resp', output=output, output_text=text,
                           usage=SimpleNamespace(input_tokens=100, output_tokens=10, input_tokens_details=SimpleNamespace(cached_tokens=90)))


class FakeClient:
    """Rounds given in order; each round may wait for an event (to hold a lookup open)."""
    def __init__(self, rounds, hold=None):
        self.rounds, self.hold, self.seen = list(rounds), hold, []
        self.responses = self

    async def create(self, **kw):
        self.seen.append(kw)
        if kw.get('max_output_tokens') == 16:
            return response([])
        if self.hold is not None:
            await self.hold.wait()
        return self.rounds.pop(0)


def open_call(monkeypatch, client):
    sent, log = [], []
    async def send(event): sent.append(event)
    monkeypatch.setattr(voice_lookup, '_client', lambda: client)
    monkeypatch.setattr(voice_lookup, 'instructions', lambda: 'instructions')
    monkeypatch.setattr(voice_lookup, 'tools', lambda: [])
    dialogue = Dialogue()
    dialogue.add('user', '尼崎駅の近くでプールがあるジム探して')
    call = voice_lookup.open_call('s', 'u', 'r', dialogue, send, lambda phase, **f: log.append((phase, f)))
    return call, sent, log


@pytest.mark.asyncio
async def test_a_lookup_returns_at_once_and_its_facts_reach_the_call(monkeypatch):
    client = FakeClient([response([call_item('web_search', {'query': '尼崎 ジム プール'}, 'c1'),
                                   call_item('share_progress', {'fact': 'プールのあるジムが2つ見つかった'}, 'c2')]),
                         response([], 'セントラルウェルネスクラブ24あまがさきに25mプールがあります。')])
    async def execute(item, user_id, room_id, dialogue, record, delegation_id, speak=None):
        assert item['name'] == 'web_search' and delegation_id.startswith('bg_')
        return {'type': 'function_call_output', 'call_id': item['call_id'], 'output': '{"found": "2件"}', 'name': item['name']}
    from app.services import voice_sideband
    monkeypatch.setattr(voice_sideband, 'execute_call', execute)
    call, sent, log = open_call(monkeypatch, client)
    out = await voice_responses.run_function('run_in_background', {'task': '尼崎駅の近くでプールがあるジム', 'label': '尼崎のプールのあるジム'}, 'u', 'r', [])
    assert out['started'] and out['id'].startswith('bg_') and '一言' in out['note']   # the delegation can end now
    await call.lookups[out['id']].task_handle
    said = [e['content'] for e in sent if e['type'] == 'session.commentary.append']
    assert said == ['調べものの途中で分かったこと: プールのあるジムが2つ見つかった',
                    '調べた結果: セントラルウェルネスクラブ24あまがさきに25mプールがあります。']
    assert all(e['delegation_id'] is None for e in sent)
    assert client.seen[-1]['previous_response_id'] == 'resp' and client.seen[-1]['input'][0]['type'] == 'function_call_output'
    assert '尼崎駅の近くでプールがあるジム探して' in client.seen[1]['input'][0]['content']   # the call's own words go with the task
    status = (await voice_responses.run_function('job_status', {}, 'u', 'r', []))
    assert status['background'][0]['state'] == 'answered'
    voice_lookup.close_call(call)


@pytest.mark.asyncio
async def test_a_correction_replaces_the_running_lookup_and_its_result_is_never_said(monkeypatch):
    hold = asyncio.Event()
    client = FakeClient([response([call_item('web_search', {'query': 'あまがさき'}, 'c1')]), response([], '古い答え')], hold=hold)
    async def execute(item, *a, **k):
        return {'type': 'function_call_output', 'call_id': item['call_id'], 'output': '{"found": "尼崎の候補"}', 'name': item['name']}
    from app.services import voice_sideband
    monkeypatch.setattr(voice_sideband, 'execute_call', execute)
    call, sent, log = open_call(monkeypatch, client)
    first = await voice_responses.run_function('run_in_background', {'task': 'あまさきのジム', 'label': 'ジム'}, 'u', 'r', [])
    old = call.lookups[first['id']]
    old.verified.append(('web_search', '{"found": "尼崎の候補"}'))
    second = await voice_responses.run_function('run_in_background', {'task': '尼崎（あまがさき）のジム', 'label': 'ジム', 'replaces': first['id']}, 'u', 'r', [])
    assert second['started'] and old.state == 'replaced'
    new = call.lookups[second['id']]
    assert '尼崎の候補' in new.carried   # what the old one verified is not searched again
    await asyncio.sleep(0)
    assert old.task_handle.cancelled() or old.task_handle.done()
    client.rounds = [response([], '新しい答え')]
    hold.set()
    await new.task_handle
    said = [e['content'] for e in sent if e['type'] == 'session.commentary.append']
    assert said == ['調べた結果: 新しい答え']
    voice_lookup.close_call(call)


@pytest.mark.asyncio
async def test_the_end_of_the_call_stops_its_lookups(monkeypatch):
    hold = asyncio.Event()
    call, sent, log = open_call(monkeypatch, FakeClient([response([], '答え')], hold=hold))
    out = await voice_responses.run_function('run_in_background', {'task': '天気', 'label': '天気'}, 'u', 'r', [])
    lookup = call.lookups[out['id']]
    voice_lookup.close_call(call)
    hold.set()
    await asyncio.sleep(0.01)
    assert lookup.state == 'cancelled' and not [e for e in sent if e['type'] == 'session.commentary.append']
    assert (await voice_responses.run_function('cancel_background', {'id': lookup.id}, 'u', 'r', []))['started'] is False
    # a call this server does not hold: the lookup is answered inline, as the delegation did before
    monkeypatch.setattr(voice_lookup, '_client', lambda: FakeClient([response([], '晴れ')]))
    assert (await voice_responses.run_function('run_in_background', {'task': '天気', 'label': '天気'}, 'u', 'r', [])) == {'answer': '晴れ'}


@pytest.mark.asyncio
async def test_a_long_answer_is_not_given_whole_its_start_is_said_and_the_whole_stays_readable(monkeypatch):
    long = 'セントラルウェルネスクラブ24あまがさきは駅から徒歩1分です。' + '料金や営業時間の詳しい話。' * 40
    call, sent, log = open_call(monkeypatch, FakeClient([response([], long)]))
    out = await voice_responses.run_function('run_in_background', {'task': 'ジム', 'label': 'ジム'}, 'u', 'r', [])
    await call.lookups[out['id']].task_handle
    kinds = [e['type'] for e in sent]
    assert kinds == ['session.commentary.append']   # nothing silent: whatever is given may be said (voice_say)
    assert sent[-1]['content'].startswith('調べた結果: セントラルウェルネスクラブ24あまがさきは駅から徒歩1分です。')
    assert len(sent[-1]['content']) <= 300
    assert call.lookups[out['id']].answer == long   # read whole when wanted (voice_router 'status')
    voice_lookup.close_call(call)


def test_the_delegation_hands_lookups_over_and_keeps_the_quick_tools(monkeypatch):
    monkeypatch.setenv('DAN_VOICE_PLAIN', '1')
    monkeypatch.delenv('DAN_VOICE_BACKGROUND', raising=False)
    backend = voice_responses.delegation(settings={'backend_model': 'gpt-6-luna', 'reasoning': 'low'})['responses']
    names = [t['name'] for t in backend['tools']]
    assert 'run_in_background' in names and 'cancel_background' in names
    assert not {'web_search', 'read_page', 'read_many', 'dan_tool', 'dan_tool_help', 'share_progress'} & set(names)
    assert {'get_saved_information', 'get_calendar', 'show_page_on_stage', 'start_work', 'end_call'} <= set(names)
    for word in ('web_search', 'dan_tool', 'read_many', 'read_page'):
        assert word not in backend['instructions']   # no rule names a tool it does not hold
    assert 'replaces' in backend['instructions']
    lookup_tools = {t['name'] for t in voice_lookup.tools()}
    assert {'web_search', 'read_page', 'places', 'browser', 'show_page_on_stage', 'share_progress'} <= lookup_tools   # given whole from the start
    assert not {'send_message_on_stage', 'start_work', 'operate_screen', 'publish_document_on_stage'} & lookup_tools


@pytest.mark.asyncio
async def test_a_lookup_asked_for_the_screen_shows_a_page_before_it_answers(monkeypatch):
    """2026-11-03 (voice_goal_call.py, 100 kg run 2): the owner asked 「商品ページ、画面に出してくれる？」, the lookup answered
    「商品ページを今、画面に出すよ」 and showed nothing; the owner had to ask again. A lookup that would answer with nothing
    shown is told once to show the page first."""
    client = FakeClient([response([], 'ボディメーカーの100kgセットが在庫ありで98,000円。商品ページを画面に出すよ。'),
                         response([call_item('show_page_on_stage', {'url': 'https://example.jp/100kg', 'conditions': '100kg・在庫あり'}, 'c1')]),
                         response([], 'ボディメーカーの100kgセットを画面に出しました。在庫ありで98,000円です。')])
    shown = []
    async def execute(item, user_id, room_id, dialogue, record, delegation_id, speak=None):
        shown.append(json.loads(item['arguments'])['url'])
        return {'type': 'function_call_output', 'call_id': item['call_id'], 'output': '{"shown": true}', 'name': item['name']}
    from app.services import voice_sideband
    monkeypatch.setattr(voice_sideband, 'execute_call', execute)
    call, sent, log = open_call(monkeypatch, client)
    call.dialogue.add('user', '実際に買えるセットの商品ページ、画面に出してくれる？')
    out = await voice_responses.run_function('run_in_background', {'task': '100kgのバーベルセットの商品ページを探す', 'label': '100kgのセット'}, 'u', 'r', [])
    await call.lookups[out['id']].task_handle
    said = [e['content'] for e in sent if e['type'] == 'session.commentary.append']
    assert shown == ['https://example.jp/100kg']
    assert said == ['調べた結果: ボディメーカーの100kgセットを画面に出しました。在庫ありで98000円です。']
    voice_lookup.close_call(call)


@pytest.mark.asyncio
async def test_a_lookup_nobody_asked_to_show_answers_without_an_extra_round(monkeypatch):
    client = FakeClient([response([], '明日の尼崎は晴れ、最高気温は18度です。')])
    async def execute(*a, **k): raise AssertionError('no tool')
    from app.services import voice_sideband
    monkeypatch.setattr(voice_sideband, 'execute_call', execute)
    call, sent, log = open_call(monkeypatch, client)
    call.dialogue.add('user', '明日の天気どう？')
    out = await voice_responses.run_function('run_in_background', {'task': '明日の尼崎の天気', 'label': '明日の天気'}, 'u', 'r', [])
    await call.lookups[out['id']].task_handle
    said = [e['content'] for e in sent if e['type'] == 'session.commentary.append']
    assert said == ['調べた結果: 明日の尼崎は晴れ、最高気温は18度です。']
    assert not any(p == 'lookup_show_reminded' for p, _ in log)
    voice_lookup.close_call(call)


def test_a_search_gives_the_lookup_the_pages_urls():
    # yoga4 (2026-11-03): with the titles alone the lookup searched ten times for a URL to show, then made one up.
    found = {'success': True, 'answer': '厚さ10mmのNBRマットが2000円台から。',
             'sources': [{'title': 'ヨガマット 10mm', 'url': 'https://item.rakuten.co.jp/shop/mat-10/'}, {'title': '一覧', 'url': ''}]}
    out = voice_responses.search_output(found, 'ヨガマット 10mm')
    assert out['pages'] == [{'title': 'ヨガマット 10mm', 'url': 'https://item.rakuten.co.jp/shop/mat-10/'}]
    assert out['found'] == found['answer']


@pytest.mark.asyncio
async def test_the_next_lookup_starts_from_what_the_answered_one_found(monkeypatch):
    # 2026-11-03 22:20 (weights_100kg): 「画面に出して」 after the price answer searched the same things again, about 8 s.
    client = FakeClient([response([call_item('web_search', {'query': '100kg セット'}, 'c1')]), response([], '4万920円から。'),
                         response([], 'ページはこれ。'), response([], '合う候補は無かった。')])
    async def execute(item, *a, **k):
        return {'type': 'function_call_output', 'call_id': item['call_id'],
                'output': '{"pages": [{"title": "IROTEC 100kg", "url": "https://shop.example/irotec-100"}], "found": "4万920円"}', 'name': item['name']}
    from app.services import voice_sideband
    monkeypatch.setattr(voice_sideband, 'execute_call', execute)
    call, sent, log = open_call(monkeypatch, client)
    first = await voice_responses.run_function('run_in_background', {'task': '100kgの重りの値段', 'label': '値段'}, 'u', 'r', [])
    await call.lookups[first['id']].task_handle
    second = await voice_responses.run_function('run_in_background', {'task': '買える商品ページを画面に出す', 'label': '画面'}, 'u', 'r', [])
    new = call.lookups[second['id']]
    assert 'https://shop.example/irotec-100' in new.carried
    await new.task_handle
    began = [kw['input'][0]['content'] for kw in client.seen if 'previous_response_id' not in kw and kw.get('max_output_tokens') != 16]
    assert len(began) == 2 and 'https://shop.example/irotec-100' in began[1]
    voice_lookup.close_call(call)
