"""The rebuilt voice entrance: one question (where is the answer?), the owner's items as answer or ingredient, words decide
hanging up. Jev and the stores are mocked; tests/../_eval/voice/intake_eval.py measures the same code with live Jev."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import voice_intake as base
from app.services import voice_intake2 as vi

SAVED = [{'field_key': 'postal_code', 'label': '郵便番号', 'category': 'address'}, {'field_key': 'etax_number', 'label': 'e-Tax 確認番号', 'category': 'identity'}]


def said(text, before=()):
    turns = [*before, {'role': 'user', 'text': text}]
    return [{'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': json.dumps({'utterance_final': True, 'dialogue': turns})}]}]


def where(place, p=.9, **others):
    return {'available': True, 'answers': {'where': {'choice': place, 'confidence': p, 'probabilities': {place: p, **others}}}}


def items(answer='none', ingredient='none', p=.9):
    pick = lambda key: {'choice': key, 'confidence': p, 'probabilities': {key: p, **({'none': round(1-p, 2)} if key != 'none' else {})}}
    return {'available': True, 'answers': {'answer': pick(answer), 'ingredient': pick(ingredient)}}


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setattr(base, 'list_owned', lambda *_: [])
    service = MagicMock(); service.list_masked_sync = lambda user: SAVED
    service.get = AsyncMock(side_effect=lambda user, key: {'label': {'postal_code': '郵便番号', 'etax_number': 'e-Tax 確認番号'}[key], 'value': {'postal_code': '660-0807', 'etax_number': '517304'}[key]})
    monkeypatch.setattr('app.services.personal_info_service.PersonalInfoService', lambda: service)
    async def no_calendar(user_id, days=14): return {}
    monkeypatch.setattr(vi, 'calendar', no_calendar)
    a = vi.VoiceIntake2('user', 'room')
    def judge(place_answer, item_answer=None, complete=None):
        async def choose(state, questions):
            if 'answer' in questions: return item_answer or items()
            if 'complete' in questions: return complete or {'available': False}
            return place_answer
        a.judge.choose = AsyncMock(side_effect=choose)
    a.set = judge
    return a


def text_of(result): return result['output'][0]['content'][0]['text']


@pytest.mark.asyncio
async def test_saved_item_is_answered_in_plain_words_with_its_reading(agent):
    agent.set(where('saved'), items('postal_code'))
    assert text_of(await agent.respond(said('俺んちの郵便番号って何番だっけ'), [], '')) == '郵便番号は、ろくろくゼロの、ゼロはちゼロなな。'


@pytest.mark.asyncio
async def test_outside_question_with_an_owner_ingredient_searches_with_the_item_travelling(agent):
    agent.set(where('web'), items(ingredient='postal_code'))
    call = (await agent.respond(said('JR尼崎駅とうちの郵便番号って同じ?'), [], ''))['output'][0]
    assert call['name'] == 'web_search' and agent.pending[call['call_id']]['saved'] == ['postal_code'] and '660' not in call['arguments']


@pytest.mark.asyncio
async def test_owner_item_is_not_the_answer_to_a_question_about_the_outside_world(agent):
    # 「JR尼崎駅の郵便番号って何番?」 matched the item name 郵便番号: answering the owner's postcode there is worse than a miss.
    agent.set(where('web'), items('postal_code'))
    call = (await agent.respond(said('JR尼崎駅の郵便番号って何番?'), [], ''))['output'][0]
    assert call['name'] == 'web_search' and not agent.pending[call['call_id']]['saved']


@pytest.mark.asyncio
async def test_a_secret_is_not_read_when_the_words_do_not_point_at_the_owner(agent):
    agent.set(where('now', .7, saved=.05), items('etax_number'))
    assert '517304' not in json.dumps(await agent.respond(said('二十四日って何だっけ'), [], ''), ensure_ascii=False)


@pytest.mark.asyncio
async def test_hanging_up_is_decided_by_the_words_and_never_asks_jev(agent):
    agent.judge.choose = AsyncMock()
    assert (await agent.respond(said('もう、お前、電話切れ'), [], ''))['output'][0]['name'] == 'enter_voice_standby'
    agent.judge.choose.assert_not_awaited()


@pytest.mark.asyncio
async def test_talk_gets_one_factual_line_and_a_lost_judgement_never_becomes_a_job(agent):
    agent.set(where('now'))
    assert text_of(await agent.respond(said('へえ、そうなんだ'), [], '')) == '調べる内容のない会話でした。'
    agent.judge.choose = AsyncMock(return_value={'available': False})
    assert text_of(await agent.respond(said('SBIの残高見てきて'), [], '')) == '裏側で内容を判定できませんでした。'


@pytest.mark.asyncio
async def test_site_goes_to_dan_and_nagging_during_a_job_gets_its_state(agent, monkeypatch):
    agent.set(where('site'))
    call = (await agent.respond(said('二十四日にカレンダーに予定入ってるよね'), [], ''))['output'][0]
    assert call['name'] == 'delegate_to_dan' and '音声通話からの依頼' in json.loads(call['arguments'])['task']
    monkeypatch.setattr(base, 'list_owned', lambda *_: [{'id': 'j', 'task': '新幹線の払い戻し確認', 'state': 'running', 'events': [{'kind': 'progress', 'text': 'EXサイトにログイン中'}]}])
    agent.set(where('now'))
    assert 'EXサイトにログイン中' in text_of(await agent.respond(said('まだですか?遅いですね'), [], ''))


@pytest.mark.asyncio
async def test_only_the_last_exchange_reaches_the_judge(agent):
    agent.set(where('now'))
    before = [{'role': 'user', 'text': f'古い話{i}'} if i % 2 == 0 else {'role': 'assistant', 'text': f'古い答え{i}'} for i in range(10)]
    await agent.respond(said('なるほど', before), [], '')
    state = next(c.args[0] for c in agent.judge.choose.await_args_list if 'where' in c.args[1])
    assert len(state['dialogue']) == 3 and state['dialogue'][-1]['text'] == 'なるほど'


@pytest.mark.asyncio
async def test_a_question_judged_as_conversation_still_looks_in_the_likely_places(agent, monkeypatch):
    # 「24日って俺なんか予定あったっけ」 was judged "conversation" and answered "no plans were mentioned".
    from app.services import voice_past
    async def gather(*a, **k): return {'records': [{'at': '', 'who': 'user', 'text': '24日は打ち合わせ'}], 'jobs': []}
    async def events(user_id, days=14): return {'events': [{'title': '東京で打ち合わせ', 'start': '2026-09-24T13:00'}]}
    monkeypatch.setattr(voice_past, 'gather', gather); monkeypatch.setattr(vi, 'calendar', events)
    class Reader:
        agent = type('A', (), {'closed': False})()
        async def read(self, dialogue, material, on_text=None): return {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(material, ensure_ascii=False)}]}]}
    agent.search_reader = Reader()
    agent.set(where('now', .5, site=.3, past=.2))
    seen = json.loads(text_of(await agent.respond(said('24日って俺なんか予定あったっけ'), [], '')))
    assert seen['calendar'][0]['title'] == '東京で打ち合わせ' and seen['past_records'][0]['text'] == '24日は打ち合わせ'   # both, at once


@pytest.mark.asyncio
async def test_nothing_found_says_where_it_looked_and_expired_calendar_goes_to_dan_with_the_way_to_reconnect(agent, monkeypatch):
    from app.services import voice_past
    async def gather(*a, **k): return {'records': [], 'jobs': []}
    monkeypatch.setattr(voice_past, 'gather', gather)
    agent.set(where('past', .8))
    assert text_of(await agent.respond(said('あの件って何て言ってたっけ'), [], '')) == '過去の会話と作業の記録を探しましたが、見つかりませんでした。'
    async def expired(user_id, days=14): return {'expired': True}
    monkeypatch.setattr(vi, 'calendar', expired)
    agent.set(where('site', .9))
    call = (await agent.respond(said('24日の予定を教えて'), [], ''))['output'][0]
    assert call['name'] == 'delegate_to_dan' and 'reconnect_url' in json.loads(call['arguments'])['task']


def test_a_plain_open_is_one_command_here_not_a_job(monkeypatch):
    opened = []
    monkeypatch.setattr(vi, 'quick_open', vi.quick_open)   # real function, faked effects
    import webbrowser, os
    monkeypatch.setattr(webbrowser, 'open', lambda u: opened.append(u) or True)
    monkeypatch.setattr(os, 'startfile', lambda t: opened.append('start:'+t), raising=False)
    assert vi.quick_open('YouTubeをパソコンで開いて') == 'YouTubeをパソコンで開きました。'
    assert vi.quick_open('メモ帳出して') == 'メモ帳をパソコンで開きました。'
    assert vi.quick_open('https://example.com/x を開いて').startswith('https://example.com/x')
    assert vi.quick_open('24日って予定あったっけ') is None and vi.quick_open('再連携の画面をパソコンに出して') is None
    assert opened == ['https://www.youtube.com/', 'start:notepad', 'https://example.com/x']
