"""Searching before the owner finishes speaking (2026-10-23).

A call's backend model asks for web_search only after the owner has stopped speaking and the speech model has handed the
turn over, and the search then takes 3-5 s. The sideband hears the owner's words while they are spoken
(session.input_transcript.delta), so the question can be recognised mid-sentence and the search started at once; when the
backend asks for the same search, the result is already there or on its way.

Recognising: Jev (one choice among search / read / work / talk / wait, about 0.15 s). Compared on 60 partial Japanese
utterances on 2026-10-23 (docs/current/search-deepseek-20261023.md): Jev 58/60 with every search found and none taken
wrongly, OpenAI Decisions 54/60 (one non-search taken for a search, and it spends the OpenAI balance a call runs on),
deepseek-flash 53/60 at 0.9 s, keyword rules 13/60 on words they were not written for. When Jev is unavailable,
deepseek-flash recognises instead. Neither writes the query: the words heard so far are the question, and web_search
writes its own queries from it.

Only searches start early: they read and change nothing, so a wrong guess costs one search (0.6 yen). Anything that
sends, pays, books or changes something still waits for the finished request and the owner's approval.

Once a turn is known to be a search, its growing words are searched again without judging (up to 3 searches a turn), so
the newest search is close to the finished sentence.

A result is used only for the same request and only once: the owner's words since the searched part may only be an ending
(「って」「教えて」「いくら？」). 「明日の天気って…いや明後日」 adds words, so the early result is dropped and the backend's
own search runs. The backend's query is not compared word by word: it rewrites the owner's words (「ドル円」 became
「USD JPY 為替レート」 in the 2026-10-23 test call), and the first search of the turn is the owner's question. That holds only
while the search is the backend's first step for the question: after another function (places for 「近くのラーメン屋」,
get_location for a weather without a place) its web_search asks something narrower that the owner's words did not, so it
runs on its own (2026-10-24 review: the ramen question's later web_search had been handed the whole question's result).

Switch: DAN_VOICE_PREFETCH=0. Logged as metadata only (counts and times, no words), like the rest of the sideband.
"""
import asyncio
import json
import os
import time

MIN_CHARS = 6          # 「えーと」「あのさ」 are not judged
STEP_CHARS = 3         # judge again once the words grew by this much
RESEARCH_CHARS = 4     # a turn known to be a search is searched again once its words grew by this much
PER_TURN = 3           # searches started early for one turn of the owner, at most
KEEP_SECONDS = 90
KINDS = {'search': 'ウェブで公開されている情報を調べる話（天気・値段・営業時間・ニュース・店・発売日など）',
         'read': 'ダンが持っている本人の情報を読む話（予定・メール・保存した住所など・前の作業の様子・本人のアカウントの中身・前に買った物）',
         'work': 'ダンに作業を頼む話（直す・作る・差し替える・下書き・リマインドを入れる）',
         'talk': '相談・雑談・返事・お礼・言い直し（調べものや作業の依頼ではない）',
         'wait': 'まだ言い始めたばかりで、何の話か分からない'}
ASK = '通話で本人が話している途中の言葉（言い終わっていないこともある）。この言葉が向かっている先として一番近いものを選ぶ。'
# what may follow the searched words without changing the question
ENDINGS = ('って', 'て', 'は', 'の', 'を', 'が', 'も', 'か', 'よ', 'ね', 'な', 'ん', 'る', 'た', 'だ', 'です', 'ですか', 'でしょう', 'だっけ',
           'かな', 'かね', '何', 'なに', 'なん', 'いくら', 'いつ', '何時', 'どこ', 'どう', 'どれくらい', 'ぐらい', 'くらい', '教えて', '調べて',
           '知りたい', '分かる', 'わかる', 'ある', 'あります', '見て', 'くれる', 'くれない', 'ちょうだい', 'ほしい', '欲しい', 'なってる', 'なった',
           'なの', 'やつ', 'とか', 'ください', 'お願い')
MARKS = set('、。？！?!　…ー〜')


def is_ending(text):
    """Is the text made only of ENDINGS and marks? Walked once over the positions the words can reach. A regular
    expression did this until 2026-10-24: 「なん」 also reads as 「な」+「ん」, and a failing match tried every split,
    4 times longer per 「なん」 (22 of them 1.6 s), on the event loop that runs every call and chat of Core."""
    reach = [True] + [False] * len(text)
    for i, ch in enumerate(text):
        if not reach[i]:
            continue
        if ch in MARKS or ch.isspace():
            reach[i + 1] = True
        for word in ENDINGS:
            if text.startswith(word, i):
                reach[i + len(word)] = True
    return reach[-1]


def enabled():
    from app.services.web_search import _env   # .env too: Core's environment does not carry it (2026-10-24 review)
    return (_env('DAN_VOICE_PREFETCH') or '1').strip() != '0'


class Early:
    def __init__(self, text, turn):
        self.text, self.turn, self.started = text, turn, time.monotonic()   # turn: the owner's turn object in Dialogue.turns
        self.task, self.used = None, False


def said_since(turns, turn):
    """The owner's words from `turn` on, joined across Dan's words in between: the transcript of the owner's last words can
    arrive after Dan has started 「調べるね」, which made 「明日の尼崎の天気って」 and 「わかる」 two turns (2026-10-23 test
    call). None when the turn is no longer kept."""
    for i, t in enumerate(turns):
        if t is turn:
            return ''.join(u['text'] for u in turns[i:] if u['role'] == 'user').strip()
    return None


def only_an_ending(searched, final):
    """Do the words after the searched part leave the question as it was? The searched part may end inside a word
    (「今のドル円ってい」+「くら」), so its last characters may be part of the ending."""
    if not final.startswith(searched):
        return False
    rest = final[len(searched):]
    return any(is_ending(searched[len(searched) - k:] + rest) for k in range(0, min(4, len(searched)) + 1))


class Prefetch:
    """One call's early searches. heard() after every delta of the owner's words; take() when the backend searches."""
    def __init__(self, user_id, record=lambda *a, **k: None):
        self.user_id, self.record = user_id, record
        self.searches = []        # Early
        self.judged = ('', None)  # (text, turn) last judged
        self.judging = None
        self.search_turn = None   # the owner's turn judged to be a search
        self.judge = None         # Jev's Decisions, opened once per call
        self.calls = []           # the owner's newest turn at each function call of the backend (newest last)
        self.counts = {'judged': 0, 'started': 0, 'hit': 0, 'missed': 0, 'jev': 0, 'flash': 0}

    @staticmethod
    def latest(turns):
        """(turn, text) of the owner's newest turn."""
        for t in reversed(turns):
            if t['role'] == 'user':
                return t, t['text'].strip()
        return None, ''

    def heard(self, dialogue):
        if not enabled() or (self.judging and not self.judging.done()):
            return
        turn, text = self.latest(dialogue.turns)
        last_text, last_turn = self.judged
        started = [s for s in self.searches if s.turn is turn]
        if turn is None or len(started) >= PER_TURN:
            return
        if turn is self.search_turn and started:
            if len(text) - len(started[-1].text) >= RESEARCH_CHARS:
                self.start(text, turn)
            return
        if len(text) < MIN_CHARS or (turn is last_turn and len(text) - len(last_text) < STEP_CHARS):
            return
        self.judged = (text, turn)
        self.judging = asyncio.ensure_future(self._judge_and_search(dialogue, text, turn))

    async def kind(self, text):
        """'search' / 'read' / 'work' / 'talk' / 'wait', or '' when no judge answered."""
        from app.services.jev_decisions import Decisions
        if self.judge is None:
            self.judge = Decisions(self.user_id, timeout=1.0, max_calls=400)
        got = await self.judge.choose({'utterance_so_far': text}, {'kind': {'type': 'choice', 'criteria': KINDS, 'instructions': ASK}})
        if got.get('available'):
            self.counts['jev'] += 1
            answer = got['answers']['kind']
            return answer['choice'] if answer['probabilities'].get(answer['choice'], 0) >= .5 else 'wait'
        self.counts['flash'] += 1
        return await self._flash(text)

    async def _flash(self, text):
        import httpx
        from app.services import web_search
        system = ('通話で本人が話している途中の言葉（言い終わっていないこともある）を見分ける係。種類: '
                  + ' / '.join(f'{k}={v}' for k, v in KINDS.items()) + '\nJSON で返す: {"kind": "..."}')
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(web_search.DEEPSEEK + '/chat/completions', headers=web_search._ds_headers(), timeout=3,
                                      json={'model': web_search.ANSWER_MODEL, 'thinking': {'type': 'disabled'}, 'max_tokens': 20,
                                            'response_format': {'type': 'json_object'},
                                            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': text}]})
            return str(json.loads(r.json()['choices'][0]['message']['content']).get('kind') or '')
        except Exception:
            return ''

    def saw_call(self, turns):
        """A function call of the backend, of any name (called before the call runs)."""
        turn, _ = self.latest(turns)
        self.calls = (self.calls + [turn])[-20:]

    def start(self, text, turn):
        from app.services import web_search
        early = Early(text, turn)
        early.task = asyncio.ensure_future(web_search.find(text, fallback=False))
        self.searches.append(early)
        self.counts['started'] += 1
        self.record('prefetch_started', chars=len(text))

    async def _judge_and_search(self, dialogue, text, turn):
        started = time.monotonic()
        try:
            kind = await self.kind(text)
        except Exception:
            kind = ''
        self.counts['judged'] += 1
        self.record('prefetch_judged', result=kind, chars=len(text), ms=round((time.monotonic() - started) * 1000))
        if kind == 'search':
            self.search_turn = turn
            self.start(text, turn)
        now = time.monotonic()
        self.searches = [s for s in self.searches if now - s.started < KEEP_SECONDS]
        self.heard(dialogue)   # words that arrived while judging

    async def take(self, query, turns):
        """The early result for the backend's web_search(query), or None. Waits for a search still running."""
        best, why = None, ''
        for s in reversed(self.searches):
            if s.used:
                continue
            final = said_since(turns, s.turn)
            if final is None or not only_an_ending(s.text, final):
                why = why or 'more_words'
                continue
            since = turns[next(i for i, t in enumerate(turns) if t is s.turn):]
            if any(c is t for c in self.calls for t in since):
                why = why or 'after_other_call'
                for o in self.searches:   # the question went another way: its early searches answer nothing
                    if o.turn is s.turn: o.used = True
                continue
            best = s
            break
        self.saw_call(turns)
        if not best:
            if why:
                self.counts['missed'] += 1
                self.record('prefetch_missed', reason=why)
            return None
        for s in self.searches:   # one turn's searches answer its first web_search only
            if s.turn is best.turn: s.used = True
        ahead = time.monotonic() - best.started
        waited = time.monotonic()
        try:
            found = await best.task
        except Exception:
            return None
        if not found.get('success'):
            return None
        self.counts['hit'] += 1
        self.record('prefetch_hit', started_before_s=round(ahead, 2), waited_ms=round((time.monotonic() - waited) * 1000),
                    search_s=found.get('seconds'))
        return found

    async def close(self):
        for s in self.searches:
            if s.task and not s.task.done():
                s.task.cancel()
        if self.judge is not None:
            await self.judge.__aexit__()
        self.record('prefetch_summary', **self.counts)
