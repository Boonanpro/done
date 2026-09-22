"""The act-choosing entrance. Jev and the stores are mocked; D:/dan-workspace/_eval/voice/acts_eval.py measures it with live Jev."""
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import voice_intake as base
from app.services import voice_intake3 as vi

SAVED = [{'field_key': 'postal_code', 'label': '郵便番号', 'category': 'address'}]
NL = chr(10)


def said(text, before=()):
    return [{'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': json.dumps({'utterance_final': True, 'dialogue': [*before, {'role': 'user', 'text': text}]})}]}]


def judged(act, p=.9, target='none', effort=2, own=0, asks=1, outside=0, again=0, **others):
    return {'available': True, 'answers': {'act': {'choice': act, 'confidence': p, 'probabilities': {act: p, **others}},
                                            'own_fact': {'type': 'noul', 'noul': own}, 'question': {'type': 'noul', 'noul': asks}, 'again': {'type': 'noul', 'noul': again},
                                            'outside': {'type': 'score', 'score': outside, 'probabilities': {}}, 'effort': {'type': 'score', 'score': effort, 'probabilities': {}},
                                            'open_target': {'choice': target, 'confidence': .9, 'probabilities': {target: .9}},
                                            'steer': {'choice': 'update', 'confidence': .9, 'probabilities': {'update': .9}}}}


def item(key='none', p=.9):
    pick = {'choice': key, 'confidence': p, 'probabilities': {key: p, **({'none': round(1-p, 2)} if key != 'none' else {})}}
    return {'available': True, 'answers': {'answer': pick, 'ingredient': {'choice': 'none', 'confidence': 1, 'probabilities': {'none': 1}}}}


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setattr(base, 'list_owned', lambda *_: [])
    service = MagicMock(); service.list_masked_sync = lambda user: SAVED
    service.get = AsyncMock(return_value={'label': '郵便番号', 'value': '660-0807'})
    monkeypatch.setattr('app.services.personal_info_service.PersonalInfoService', lambda: service)
    a = vi.VoiceIntake3('user', 'room')

    def judge(act_answer, item_answer=None):
        async def choose(state, questions):
            return (item_answer or item()) if 'answer' in questions else act_answer
        a.judge.choose = AsyncMock(side_effect=choose)
    a.set = judge
    return a


def text_of(r): return r['output'][0]['content'][0]['text']


@pytest.mark.asyncio
async def test_talk_and_acceptances_go_back_silently_facts_aloud(agent):
    agent.set(judged('talk', asks=.1))
    r = await agent.respond(said('なるほどね'), [], '')
    assert r['silent'] and r['output'][0]['type'] == 'message'
    agent.set(judged('saved'), item('postal_code'))
    r = await agent.respond(said('俺の郵便番号なんだっけ'), [], '')
    assert not r.get('silent') and text_of(r) == '郵便番号は、ろくろくゼロの、ゼロはちゼロなな。'
    agent.set(judged('work'))
    call = (await agent.respond(said('SBIの残高見てきて'), [], ''))['output'][0]
    accepted = await agent.respond([{'type': 'function_call_output', 'call_id': call['call_id'], 'output': json.dumps({'accepted': True})}], [], '')
    assert accepted['silent']   # 「受け付けました」 is never spoken


@pytest.mark.asyncio
async def test_a_saved_item_that_fits_wins_over_talk(agent, monkeypatch):
    monkeypatch.setattr(vi.saved_items, 'direct', True, raising=False)
    agent.set(judged('talk', own=.7, saved=.2), item('postal_code'))
    assert text_of(await agent.respond(said('もう一回確認して', [{'role': 'assistant', 'text': '660の807です。'}]), [], '')) == '郵便番号は、ろくろくゼロの、ゼロはちゼロなな。'


@pytest.mark.asyncio
async def test_known_target_opens_here_even_when_the_act_said_work(agent, monkeypatch):
    opened = []
    monkeypatch.setattr(vi, 'open_target', lambda name: opened.append(name) or f'{name}をパソコンで開きました。')
    agent.set(judged('work', target='YouTube', effort=.2))   # one command on a known target: not a job
    assert text_of(await agent.respond(said('おい黙れ、俺のパソコンでYouTube開け'), [], '')) == 'YouTubeをパソコンで開きました。' and opened == ['YouTube']
    agent.set(judged('open', target='none'))
    assert (await agent.respond(said('その画面をパソコンに出して'), [], ''))['output'][0]['name'] == 'delegate_to_dan'


@pytest.mark.asyncio
async def test_running_job_status_steer_and_finished_result(agent, monkeypatch):
    running = {'id': 'j', 'state': 'running', 'task': 'EXの払い戻し確認', 'events': [], 'current_tool': {'name': 'browser', 'action': 'fill_credential'},
               'last_observation': {'text': 'URL: https://shinkansen2.jr-central.co.jp/x'+NL+'タイトル: スマートEX ログイン'}}
    monkeypatch.setattr(base, 'list_owned', lambda *_: [running])
    agent.set(judged('job_status'))
    assert 'スマートEX ログイン' in text_of(await agent.respond(said('今何してんの'), [], ''))
    agent.set(judged('job_steer'))
    call = (await agent.respond(said('0awの方を見て'), [], ''))['output'][0]
    assert call['name'] == 'control_dan_task' and json.loads(call['arguments'])['operation'] == 'update'
    done = {'id': 'j', 'state': 'completed', 'task': '24日の予定を見て', 'result': 'shubのカレンダーに24日の予定は無し', 'updated_at': datetime.now(timezone.utc).isoformat(), 'events': []}
    monkeypatch.setattr(base, 'list_owned', lambda *_: [done])
    agent.set(judged('result'))
    r = await agent.respond(said('どっちのカレンダー見てるの'), [], '')
    assert r['silent'] and 'shubのカレンダー' in text_of(r)


@pytest.mark.asyncio
async def test_low_confidence_question_gathers_instead_of_starting_a_job(agent, monkeypatch):
    from app.services import voice_past
    monkeypatch.setattr(voice_past, 'gather', AsyncMock(return_value={'records': [{'at': '', 'who': 'user', 'text': '24日は東京'}], 'jobs': []}))

    class Reader:
        agent = type('A', (), {'closed': False})()
        async def read(self, dialogue, material, on_text=None):
            return {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(material, ensure_ascii=False)}]}]}
    agent.search_reader = Reader()
    agent.set(judged('work', .3, past=.3, talk=.3))
    assert '24日は東京' in text_of(await agent.respond(said('24日って何かあったっけ'), [], ''))
    agent.judge.choose = AsyncMock(return_value={'available': False})
    assert (await agent.respond(said('残高見て'), [], ''))['silent']


@pytest.mark.asyncio
async def test_hang_up_is_an_act_not_a_pattern(agent):
    agent.set(judged('end'))
    assert (await agent.respond(said('もういいわ、またね'), [], ''))['output'][0]['name'] == 'enter_voice_standby'
