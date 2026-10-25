import asyncio
import time

import pytest

from app.services import web_search as W


@pytest.fixture
def deepseek(monkeypatch):
    behaviour = {'kind': 'ok', 'wait': 0}
    async def run(query):
        await asyncio.sleep(behaviour['wait'])
        if behaviour['kind'] == 'fail': raise RuntimeError('deepseek down')
        return {'answer': '' if behaviour['kind'] == 'empty' else 'ans:' + query, 'sources': []}
    monkeypatch.setattr(W, '_deepseek', run)
    monkeypatch.setattr(W, 'SECONDS', .2)
    return behaviour


@pytest.mark.asyncio
async def test_an_answer(deepseek):
    found = await W.find('q')
    assert found['success'] and found['answer'] == 'ans:q'


@pytest.mark.asyncio
async def test_a_slow_deepseek_ends_within_the_limit(deepseek):
    deepseek['wait'] = 5
    started = time.perf_counter()
    found = await W.find('q')
    assert not found['success'] and '秒で答えが返らなかった' in found['error'] and time.perf_counter() - started < .4


@pytest.mark.asyncio
async def test_a_failure_or_an_empty_answer_says_so(deepseek):
    deepseek['kind'] = 'fail'
    assert 'deepseek down' in (await W.find('q'))['error']
    deepseek['kind'] = 'empty'
    assert not (await W.find('q'))['success']
