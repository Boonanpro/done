import asyncio
import time

import pytest

from app.services import web_search as W


@pytest.fixture
def engines(monkeypatch):
    calls = []
    behaviour = {'deepseek': ('ok', 0), 'openai': ('ok', 0)}
    async def run(name, query):
        calls.append(name)
        kind, wait = behaviour[name]
        await asyncio.sleep(wait)
        if kind == 'fail': raise RuntimeError(name + ' down')
        return {'answer': '' if kind == 'empty' else name + ':' + query, 'sources': []}
    monkeypatch.setattr(W, '_deepseek', lambda q: run('deepseek', q))
    monkeypatch.setattr(W, '_openai', lambda q: run('openai', q))
    monkeypatch.setattr(W, 'engine', lambda: 'deepseek')
    monkeypatch.setattr(W, 'DEEPSEEK_SECONDS', .2)
    monkeypatch.setattr(W, 'TOTAL_SECONDS', .5)
    monkeypatch.setattr(W, '_deepseek_down', [0.0])
    return calls, behaviour


@pytest.mark.asyncio
async def test_a_slow_deepseek_hands_over_to_openai_in_time(engines):
    calls, behaviour = engines
    behaviour['deepseek'] = ('ok', 5)
    started = time.perf_counter()
    found = await W.find('q')
    assert found['success'] and found['engine'] == 'openai' and time.perf_counter() - started < .4
    found = await W.find('q2')   # DeepSeek is skipped for a while after that
    assert found['engine'] == 'openai' and calls == ['deepseek', 'openai', 'openai']


@pytest.mark.asyncio
async def test_the_whole_search_ends_within_the_total(engines):
    calls, behaviour = engines
    behaviour['deepseek'] = ('ok', 5)
    behaviour['openai'] = ('ok', 5)
    started = time.perf_counter()
    found = await W.find('q')
    assert not found['success'] and '時間切れ' in found['error'] and time.perf_counter() - started < .7


@pytest.mark.asyncio
async def test_early_searches_never_fall_back_to_openai(engines):
    calls, behaviour = engines
    behaviour['deepseek'] = ('fail', 0)
    assert not (await W.find('q', fallback=False))['success'] and calls == ['deepseek']
    assert not (await W.find('q', fallback=False))['success'] and calls == ['deepseek']   # skipped while down: no call
    assert (await W.find('q'))['engine'] == 'openai'


@pytest.mark.asyncio
async def test_an_empty_answer_falls_back_without_skipping_deepseek_later(engines):
    calls, behaviour = engines
    behaviour['deepseek'] = ('empty', 0)
    assert (await W.find('q'))['engine'] == 'openai'
    behaviour['deepseek'] = ('ok', 0)
    assert (await W.find('q'))['engine'] == 'deepseek'
