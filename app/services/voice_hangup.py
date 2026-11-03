"""The owner's 「切って」 ends the call even while the backend is busy (2026-11-03).

Why: in the 13:35 call the owner said 「ちょっと電話切って」 while the backend was still redoing a product page. The speech
model hands work to one backend turn at a time, so the hang-up never reached end_call; Dan said 「うん、切るね」 and then
「切れたよ」 to 「切れますか」, and the owner answered 「切れてないよ電話」. Here the server hears the owner's words itself: words
that may be a hang-up (a cheap pattern first) are judged by Jev in the conversation's context, and a request to end THIS
call ends it the way end_call does, after Dan's goodbye has been said. Nothing is said into the call.

Switch: DAN_VOICE_HANGUP=0.
"""
import asyncio
import os
import re
import time

SETTLE_S = .7        # the owner's words settle before they are judged
QUIET_S = 1.2        # Dan's goodbye has ended when his voice was quiet this long
MAX_GOODBYE_S = 6.0  # the call closes at the latest this long after the request
CUE = re.compile(r'切[っらりるれろ]|きって|きる[ねよ]|電話.*(終|おわ)|通話.*(終|おわ)|終わりに|おわりに|終わろ|おわろ|バイバイ|ばいばい|またね|じゃあね|失礼します')


def enabled():
    return os.environ.get('DAN_VOICE_HANGUP', '1') != '0'


class HangUp:
    def __init__(self, user_id, dialogue, record, end, judge=None):
        """`end()` ends the call (marks it ending and closes it); `judge(text, turns)` -> True for a hang-up request."""
        self.user_id, self.dialogue, self.record, self.end = user_id, dialogue, record, end
        self.judge = judge or self._jev
        self._timer, self._judged, self.done = None, '', False
        self._decisions = None

    def heard(self):
        if self.done: return
        if self._timer is not None: self._timer.cancel()
        self._timer = asyncio.ensure_future(self._after())

    def latest(self):
        for t in reversed(self.dialogue.turns):
            if t['role'] == 'user': return t['text'].strip()
        return ''

    async def _after(self):
        await asyncio.sleep(SETTLE_S)
        text = self.latest()
        if self.done or not text or text == self._judged or not CUE.search(text[-40:]): return
        self._judged = text
        try: asked = await self.judge(text[-200:], self.dialogue.turns[-8:])
        except Exception: asked = False
        self.record('hangup_judged', asked=bool(asked))
        if asked and not self.done:
            self.done = True
            await self.end()

    async def close(self):
        self.done = True
        if self._timer is not None: self._timer.cancel()
        if self._decisions is not None:
            try: await self._decisions.__aexit__()
            except Exception: pass

    async def _jev(self, text, turns):
        if self._decisions is None:
            from app.services.jev_decisions import Decisions
            self._decisions = Decisions(self.user_id, timeout=1.5, max_calls=40, retry_transient_after=10)
        got = await self._decisions.choose({'caller_words': text, 'conversation': [dict(t) for t in turns]}, {'hangup': {
            'type': 'choice', 'criteria': {
                'end': '本人が、今のこの通話（電話）を終えてほしい・切ってほしいと頼んでいる、または別れのあいさつで通話を終えようとしている。',
                'other': 'それ以外。文章や動画を切る・短くする話、作業を終わらせる話、通話を切ったかの確認だけ、通話を終えるかの相談、または曖昧。'},
            'instructions': '通話の文脈で、本人が今この通話を終えたいのかだけを判断する。'}})
        answer = (got.get('answers') or {}).get('hangup') or {}
        return bool(got.get('available') and answer.get('choice') == 'end' and (answer.get('probabilities') or {}).get('end', 0) >= .8)


async def after_goodbye(last_spoke, close, started=None):
    """Close once Dan's voice has been quiet for QUIET_S (his 「切るね」 is not cut off), at the latest MAX_GOODBYE_S."""
    started = time.monotonic() if started is None else started
    await asyncio.sleep(QUIET_S)
    while time.monotonic() - started < MAX_GOODBYE_S and time.monotonic() - last_spoke() < QUIET_S:
        await asyncio.sleep(.2)
    await close()
