import asyncio

import pytest

from app.services import voice_prefetch as P
from app.services import voice_sideband as S


@pytest.fixture
def fake(monkeypatch):
    searched = []
    async def find(text):
        searched.append(text)
        await asyncio.sleep(.01)
        return {'success': True, 'answer': 'ans:' + text, 'sources': [], 'engine': 'deepseek', 'seconds': .01}
    monkeypatch.setattr('app.services.web_search.find', find)
    kinds = {}
    async def kind(self, text):
        return next((k for prefix, k in kinds.items() if text.startswith(prefix)), 'wait')
    monkeypatch.setattr(P.Prefetch, 'kind', kind)
    return searched, kinds


async def speak(d, pre, role, *parts):
    for part in parts:
        d.add(role, part)
        if role == 'user':
            pre.heard(d)
        await asyncio.sleep(.02)


@pytest.mark.asyncio
async def test_a_question_is_searched_while_spoken_and_used_once(fake):
    searched, kinds = fake
    kinds['明日の尼崎'] = 'search'
    d, pre = S.Dialogue(), P.Prefetch('u')
    await speak(d, pre, 'user', '明日の', '尼崎の天', '気って', 'わかる？')
    await speak(d, pre, 'assistant', '調べるね')
    assert searched and all(s.startswith('明日の尼崎') for s in searched)
    found = await pre.take('尼崎 天気 10月24日', d.turns)
    assert found and found['answer'].startswith('ans:明日の尼崎')
    assert await pre.take('尼崎 天気 10月25日', d.turns) is None   # a second search of the turn runs on its own


@pytest.mark.asyncio
async def test_words_after_dan_started_still_belong_to_the_question(fake):
    """The owner's last words can be transcribed after Dan's 「調べるね」: they are one question."""
    searched, kinds = fake
    kinds['今のドル円'] = 'search'
    d, pre = S.Dialogue(), P.Prefetch('u')
    await speak(d, pre, 'user', '今のドル円って', 'い')
    await speak(d, pre, 'assistant', '見てくるね')
    await speak(d, pre, 'user', 'くら')
    assert await pre.take('USD JPY 為替レート', d.turns)   # the backend's own wording does not matter


@pytest.mark.asyncio
async def test_a_changed_question_drops_the_early_result(fake):
    searched, kinds = fake
    kinds['明日の天気'] = 'search'
    d, pre = S.Dialogue(), P.Prefetch('u')
    await speak(d, pre, 'user', '明日の天気って')
    await asyncio.sleep(.05)
    d.add('user', 'いうか明後日の大阪')   # spoken after the last search, nothing searched it
    assert await pre.take('大阪 天気 明後日', d.turns) is None


@pytest.mark.asyncio
async def test_growing_words_are_searched_again_without_judging(fake, monkeypatch):
    searched, kinds = fake
    kinds['尼崎駅の近く'] = 'search'
    d, pre = S.Dialogue(), P.Prefetch('u')
    await speak(d, pre, 'user', '尼崎駅の近くで', '美味しいラーメン', '屋さんを', '教えて')
    assert len(searched) >= 2 and len(searched) <= P.PER_TURN
    found = await pre.take('尼崎駅 ラーメン', d.turns)
    assert found and found['answer'] == 'ans:' + searched[-1]


@pytest.mark.asyncio
async def test_nothing_is_searched_for_talk_or_work(fake):
    searched, kinds = fake
    kinds['LPのあの部分'] = 'work'
    d, pre = S.Dialogue(), P.Prefetch('u')
    await speak(d, pre, 'user', 'LPのあの部分を', '直して')
    await speak(d, pre, 'user', 'えーと')
    assert searched == [] and await pre.take('x', d.turns) is None


def test_endings():
    assert P.only_an_ending('今のドル円ってい', '今のドル円っていくら？')
    assert P.only_an_ending('明日の尼崎の天気って', '明日の尼崎の天気ってわかる')
    assert not P.only_an_ending('明日の天気って', '明日の天気っていうか明後日')
    assert not P.only_an_ending('Amazonで', 'Amazonで注文しなくていい')
