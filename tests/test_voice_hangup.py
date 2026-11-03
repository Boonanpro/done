import asyncio
import time

import pytest

from app.services import voice_hangup as H
from app.services.voice_sideband import Dialogue


def hangup(judged, monkeypatch):
    monkeypatch.setattr(H, 'SETTLE_S', .01)
    dialogue, ended, log, asked = Dialogue(), [], [], []
    async def judge(text, turns):
        asked.append(text)
        return judged(text)
    async def end(): ended.append(True)
    return H.HangUp('u1', dialogue, lambda phase, **f: log.append((phase, f)), end, judge=judge), dialogue, ended, asked


@pytest.mark.asyncio
async def test_the_owners_hang_up_ends_the_call_while_the_backend_is_busy(monkeypatch):
    # 2026-11-03 13:38: 「ちょっと電話切って」 during a backend turn never reached end_call; Dan said 「切れたよ」 and it was not.
    h, dialogue, ended, asked = hangup(lambda text: '切って' in text, monkeypatch)
    dialogue.add('user', 'ごめん、やっぱ、ちょっと電話切って'); h.heard()
    await asyncio.sleep(.05)
    assert ended == [True] and asked == ['ごめん、やっぱ、ちょっと電話切って']
    dialogue.add('user', '切れますか'); h.heard()
    await asyncio.sleep(.05)
    assert ended == [True] and len(asked) == 1   # once


@pytest.mark.asyncio
async def test_words_without_a_hang_up_cue_are_not_judged(monkeypatch):
    h, dialogue, ended, asked = hangup(lambda text: True, monkeypatch)
    dialogue.add('user', '百キロぐらいの重りを家にそろえたらいくら'); h.heard()
    await asyncio.sleep(.05)
    assert ended == [] and asked == []


@pytest.mark.asyncio
async def test_a_cut_that_is_not_the_call_does_not_end_it(monkeypatch):
    h, dialogue, ended, asked = hangup(lambda text: False, monkeypatch)
    dialogue.add('user', 'その動画の最初の5秒切って'); h.heard()
    await asyncio.sleep(.05)
    assert ended == [] and asked == ['その動画の最初の5秒切って']


@pytest.mark.asyncio
async def test_the_call_closes_after_dans_goodbye(monkeypatch):
    monkeypatch.setattr(H, 'QUIET_S', .05); monkeypatch.setattr(H, 'MAX_GOODBYE_S', 1)
    spoke = {'at': time.monotonic()}
    closed = []
    async def close(): closed.append(time.monotonic())
    async def talking():
        for _ in range(4):
            await asyncio.sleep(.03); spoke['at'] = time.monotonic()
    started = time.monotonic()
    await asyncio.gather(H.after_goodbye(lambda: spoke['at'], close, started), talking())
    assert closed and closed[0] - spoke['at'] >= .05 - .01
