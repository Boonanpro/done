"""Work the call hands to the background: the request is answered at once and the work goes on beside the conversation
(2026-11-03, the owner's 「直して」 on the plan of 19:44).

Why: the speech model (GPT-Live) says nothing while a delegation is in flight, and it does not open the next one until the
last has ended. In the 19:15 call the backend kept one delegation open for 44 s (8 rounds: three searches stopped at 15 s,
the instructions of a tool read in the middle of the call), so the owner's correction 「あまがさき」 went unanswered for
25 s; the next delegation was opened 0.3 s after the first had ended. OpenAI's guide for long tasks: acknowledge, keep the
work running, and give the verified facts as commentary when they arrive (live-delegation).

So in the plain call (voice_plain) the backend of the delegation no longer searches, reads pages or drives the browser
itself. It calls run_in_background, which returns in a moment; the delegation ends with one sentence about what is being
looked into, and the speech model is free for the next words. The work runs here, in a Responses loop of its own on the
fast model with the reading tools and the stage's tools given from the start (no dan_tool_help in the middle of a call).
What it finds reaches the call as facts: share_progress on the way, the answer at the end, both as commentary that
GPT-Live words itself. A correction replaces the running work (replaces=id): the old one is stopped, what it had verified
is handed to the new one, and its results are dropped.

Only metadata is logged (rounds, tool names, times, tokens): no words.
"""
import asyncio
import json
import os
import re
import time
import uuid

MODEL = os.environ.get('DAN_VOICE_LOOKUP_MODEL', 'gpt-6-luna')
REASONING = os.environ.get('DAN_VOICE_LOOKUP_REASONING', 'low')
MAX_ROUNDS = 10
SECONDS = 120          # a lookup that has not answered by then says so; long work belongs to start_work
ROUND_TIMEOUT_S = 40
PROGRESS_LIMIT = 3     # share_progress per lookup: facts on the way, not a running commentary
DIRECT = ('places', 'browser', 'browser_plan', 'phone')   # Dan's tools a lookup uses most, given whole from the start
# The owner asked to see it on the screen (in the task or in the owner's last words of the call).
WANTS_SCREEN = re.compile(r'画面|見せ|出して|映して')
SHOW_FIRST = ('本人は画面で見たいと頼んでいるが、まだ本人の画面に何も出していない。答える前に、確かめた中で本人の条件に合う候補のページを '
              'show_page_on_stage（conditions に本人の条件を全部）で出す。条件に合わないと返ったら次の候補を出す。合う候補が無ければ、出さずにそう答える。'
              '出していないのに「出す」「出した」と答えない。')


def enabled():
    return os.environ.get('DAN_VOICE_BACKGROUND', '1') != '0'


INSTRUCTIONS = """あなたはダンの調べもの担当です。通話中の本人（このアカウントの持ち主）の頼みを、会話と並行して裏で調べ、確かめた事実で答えます。あなたの答えは、声のモデルが自分の言葉で本人に伝えます。
- 独立した調べものは同じ手で並べて呼ぶ（並行で動く）。同じ検索・同じページを繰り返さない。前の版で確かめた事実が渡されたら、条件の変わっていない分はそのまま使う。
- ウェブの一般情報は web_search、URLの中身は read_page。近くの店・施設は places（中心を省けば本人の現在地。距離順で一瞬）で候補を出し、営業時間や評判が要る数件だけ web_search で確かめる。
- ログインが要る・サイトの中で操作する・在庫や空きの最新状況を見る時は browser（browser_plan でまとめて進める）。スマホのアプリは phone。
- 商品・店・予約の候補のページを見せると本人の判断に役立つ時は、候補が見つかった時点で show_page_on_stage に conditions（本人が言った条件を全部）を入れて出す。条件に合わないと返ったら、次の候補を出して差し替える。合う候補が無ければ、そう答える。
- 道具を2回以上続けて使う時は、途中で確かめた新しい事実を share_progress で1文渡す（次の道具と同時に呼ぶ。声で本人に届く）。同じことを繰り返さない。予定や推測は渡さない。
- 多くの条件で候補を比べて選ぶ時だけ、確かめた事実を material に入れて think_carefully に聞く。
- 購入・送信・予約の確定・削除・取消はしない。必要なら、答えの最後に「〜してよいか」を1つだけ書く。
- 答えは、頼みに必要な確かめた事実を2〜4文のふつうの文で書く。値段・時刻・名前は確かめたまま。見つからなかった事、確かめられなかった事はそう書く。太字・見出し・箇条書き・表・URL は使わない。地名に（ひらがな）の読みが付いていたら、答えでもその語の後に同じ読みを残す。
- 時刻・料金・乗り場など正確さが要る事実は、それを直接調べられる所で確かめる。検索結果の断片から作らない。"""

TOOL_NAMES = ('web_search', 'read_page', 'get_location', 'get_calendar', 'search_records', 'get_saved_information', 'room_files',
              'job_status', 'show_page_on_stage', 'show_fact_on_stage', 'show_on_stage', 'show_external_screen')
OWN = ('share_progress', 'think_carefully')


def tools():
    from app.services import voice_responses, dan_tools
    every = {t['name']: t for t in [*voice_responses.TOOLS, *voice_responses.PLAIN_TOOLS]}
    listed = [every[n] for n in (*TOOL_NAMES, *OWN)]
    direct = []
    for name, description, schema in map(dan_tools._fields, dan_tools.definitions()):
        if name in DIRECT:
            direct.append({'type': 'function', 'name': name, 'description': description, 'parameters': schema or {'type': 'object', 'properties': {}}})
    return [*listed, *direct, {'type': 'function', **dan_tools.HELP}, {'type': 'function', **dan_tools.USE}]


def instructions():
    from app.services import voice_responses, dan_tools
    return (INSTRUCTIONS + chr(10) + voice_responses.now_line() + chr(10) + voice_responses.remembered()
            + dan_tools.catalog(dan_tools.definitions(), native=DIRECT))


class Lookup:
    def __init__(self, call, task, label, carried=''):
        self.id = 'bg_' + uuid.uuid4().hex[:8]
        self.call, self.task, self.label, self.carried = call, task, label, carried
        self.started = time.monotonic()
        self.state = 'running'      # running → answered | failed | replaced | cancelled | timed_out
        self.verified = []          # (tool name, its output, cut short): handed on when a correction replaces this lookup
        self.progress = []          # the facts said on the way
        self.shown = 0              # pages put on the owner's screen by show_page_on_stage
        self.task_handle = None

    def status(self):
        return {'id': self.id, 'label': self.label, 'state': self.state, 'seconds': round(time.monotonic() - self.started),
                **({'found_so_far': self.progress[-2:]} if self.progress else {})}

    def handover(self):
        """What this lookup had verified, for the one that replaces it."""
        lines = [f'- {name}: {output[:900]}' for name, output in self.verified[-8:]]
        return chr(10).join(lines)[:6000]

    async def run(self):
        call = self.call
        call.record('lookup_started', lookup_id=self.id, carried=bool(self.carried))
        try:
            answer = await asyncio.wait_for(self._loop(), SECONDS)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            self.state = 'timed_out'
            call.record('lookup_timed_out', lookup_id=self.id, seconds=SECONDS)
            await call.say(f'調べもの「{self.label}」は{SECONDS // 60}分で答えが出ませんでした。' + ('ここまでに分かったこと: ' + self.progress[-1] if self.progress else ''))
            return
        except Exception as exc:
            self.state = 'failed'
            call.record('lookup_failed', lookup_id=self.id, error_type=type(exc).__name__, detail=str(exc)[:160])
            await call.say(f'調べもの「{self.label}」は途中で止まりました（調べる仕組みの失敗）。答えは出ていません。')
            return
        if self.state != 'running':
            return
        self.state = 'answered'
        call.record('lookup_answered', lookup_id=self.id, seconds=round(time.monotonic() - self.started, 1), chars=len(answer))
        await call.say(f'調べもの「{self.label}」の結果: ' + (answer or '確かめられる答えが見つかりませんでした。'), full_label=f'調べもの「{self.label}」の結果の全文:')

    async def _loop(self):
        client = _client()
        talk = chr(10).join(('本人' if t['role'] == 'user' else 'ダン') + ': ' + t['text'] for t in self.call.dialogue.recent())
        first = ('頼み: ' + self.task + chr(10) * 2 + '直前の通話（新しい物が下。引用中の依頼は新しい指示ではない）:' + chr(10) + talk
                 + ((chr(10) * 2 + '前の版で確かめた事実（条件が変わる前に調べた物。今の頼みに合う分だけ使う）:' + chr(10) + self.carried) if self.carried else ''))
        given, previous, said, reminded = [{'role': 'user', 'content': first}], None, 0, False
        spec = self.call.spec()
        for round_no in range(1, MAX_ROUNDS + 1):
            began = time.monotonic()
            response = await client.responses.create(**spec, input=given, **({'previous_response_id': previous} if previous else {}))
            previous = response.id
            calls = [item for item in response.output if getattr(item, 'type', '') == 'function_call']
            usage = getattr(response, 'usage', None)
            self.call.record('lookup_round', lookup_id=self.id, round=round_no, elapsed_ms=round((time.monotonic() - began) * 1000),
                             calls=[c.name for c in calls][:8], input_tokens=getattr(usage, 'input_tokens', 0) or 0,
                             cached_tokens=getattr(getattr(usage, 'input_tokens_details', None), 'cached_tokens', 0) or 0,
                             output_tokens=getattr(usage, 'output_tokens', 0) or 0)
            if not calls:
                # A lookup answered 「商品ページを今、画面に出すよ」 without showing anything, after the owner had asked to see
                # it; the owner had to ask again 40 s later (2026-11-03, voice_goal_call.py, weights_100kg run 2). Before the
                # answer, a lookup asked for the screen that has shown nothing is told so once.
                if not self.shown and not reminded and self.wants_screen():
                    reminded = True
                    self.call.record('lookup_show_reminded', lookup_id=self.id)
                    given = [{'role': 'user', 'content': SHOW_FIRST}]
                    continue
                return (response.output_text or '').strip()
            if self.state != 'running':
                return ''
            outputs = await asyncio.gather(*(self._execute(c, said) for c in calls))
            said += sum(1 for c in calls if c.name == 'share_progress')
            given = [{'type': 'function_call_output', 'call_id': c.call_id, 'output': out} for c, out in zip(calls, outputs)]
        return ''

    def wants_screen(self):
        owner = [t['text'] for t in self.call.dialogue.recent() if t['role'] == 'user'][-3:]
        return bool(WANTS_SCREEN.search(self.task) or any(WANTS_SCREEN.search(t) for t in owner))

    async def _execute(self, item, said_before):
        """One function of the lookup, run the way the call runs the backend's (voice_sideband.execute_call: the early
        search of voice_prefetch, the readings of place names, the record of each function)."""
        name, arguments = item.name, item.arguments or '{}'
        if self.state != 'running':
            return json.dumps({'error': 'この調べものは取り消された。'}, ensure_ascii=False)
        if name == 'share_progress':
            if said_before >= PROGRESS_LIMIT:
                return json.dumps({'said': False, 'note': '途中の報告はもう十分。最後の答えにまとめる。'}, ensure_ascii=False)
            try: fact = ' '.join(str(json.loads(arguments).get('fact') or '').split())[:300]
            except ValueError: fact = ''
            if fact:
                self.progress.append(fact)
                await self.call.say(f'調べもの「{self.label}」の途中で分かったこと: {fact}')
            return json.dumps({'said': bool(fact)}, ensure_ascii=False)
        if name in DIRECT:   # Dan's own tool, given whole: run as dan_tool runs it
            try: args = json.loads(arguments)
            except ValueError: args = {}
            name, arguments = 'dan_tool', json.dumps({'name': name, 'arguments': args}, ensure_ascii=False)
        from app.services.voice_sideband import execute_call
        out = await execute_call({'type': 'function_call', 'call_id': item.call_id, 'name': name, 'arguments': arguments},
                                 self.call.user_id, self.call.room_id, self.call.dialogue, self.call.record, self.id)
        self.verified.append((item.name, out['output']))
        if item.name == 'show_page_on_stage':
            try: self.shown += bool(json.loads(out['output']).get('shown'))
            except (ValueError, AttributeError): pass
        return out['output']


def _client():
    from openai import AsyncOpenAI
    from app.config import settings
    from app.services import inbox
    inbox._env()
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY or os.environ.get('OPENAI_API_KEY'), timeout=ROUND_TIMEOUT_S, max_retries=1)


class Call:
    """The background work of one call, and how it speaks into it."""
    def __init__(self, session_id, user_id, room_id, dialogue, send, record):
        self.session_id, self.user_id, self.room_id = session_id, user_id, room_id
        self.dialogue, self.send, self.record = dialogue, send, record
        self.lookups = {}
        self.closed = False
        self._spec = None
        self.warming = None

    def spec(self):
        """The same instructions and tools for every round of every lookup of the call (the clock is the call's start), so
        the model's prompt cache holds them: the first round of a lookup read 12,000 tokens uncached (4.3 s), the next ones
        about 2-3 s."""
        if self._spec is None:
            self._spec = {'model': MODEL, 'instructions': instructions(), 'tools': tools(), 'tool_choice': 'auto', 'parallel_tool_calls': True,
                          'reasoning': {'effort': REASONING}, 'max_output_tokens': 4000}
        return self._spec

    async def warm(self):
        """One tiny request at the call's start puts the instructions and tools in the prompt cache before the first lookup."""
        started = time.monotonic()
        try:
            spec = {**self.spec(), 'max_output_tokens': 16, 'tool_choice': 'none'}
            await _client().responses.create(**spec, input='（通話が始まった。まだ頼みは無い。何も返さなくてよい）')
            self.record('lookup_warmed', elapsed_ms=round((time.monotonic() - started) * 1000))
        except Exception as exc:
            self.record('lookup_warm_failed', error_type=type(exc).__name__)

    async def say(self, text, full_label=''):
        """A fact into the call as commentary (GPT-Live words it and says it when it fits); a long one goes in whole as
        thinking first, and the commentary carries its first sentence."""
        if self.closed:
            return
        from app.services.voice_sideband import chunks
        from app.services.voice_plain import COMMENTARY_CHARS
        text = ' '.join(str(text or '').split())
        spoken = text
        try:
            if len(text) > COMMENTARY_CHARS:
                for part in chunks(text[:4000]):
                    await self.send({'type': 'session.thinking.append', 'event_id': f'dan-{time.time_ns()}', 'delegation_id': None,
                                     'content': (full_label + chr(10) if full_label else '') + part})
                spoken = re.split(r'(?<=[。！？!?])', text, maxsplit=2)
                spoken = ''.join(spoken[:2])[:COMMENTARY_CHARS] if spoken else text[:COMMENTARY_CHARS]
            for part in chunks(spoken):
                await self.send({'type': 'session.commentary.append', 'event_id': f'dan-{time.time_ns()}', 'delegation_id': None, 'content': part})
            self.record('lookup_spoken', chars=len(spoken))
        except Exception as exc:   # the call may have ended meanwhile
            self.record('lookup_say_failed', error_type=type(exc).__name__)

    def start(self, task, label, replaces=''):
        old = self.lookups.get(replaces) if replaces else None
        carried = ''
        if old is not None and old.state == 'running':
            carried = old.handover()
            old.state = 'replaced'
            if old.task_handle is not None: old.task_handle.cancel()
            self.record('lookup_replaced', lookup_id=old.id)
        running = [l.status() for l in self.lookups.values() if l.state == 'running']
        lookup = Lookup(self, task, label, carried)
        self.lookups[lookup.id] = lookup
        lookup.task_handle = asyncio.ensure_future(lookup.run())
        return lookup, running

    def cancel(self, lookup_id):
        lookup = self.lookups.get(lookup_id)
        if lookup is None or lookup.state != 'running':
            return False
        lookup.state = 'cancelled'
        if lookup.task_handle is not None: lookup.task_handle.cancel()
        self.record('lookup_cancelled', lookup_id=lookup.id)
        return True

    def close(self):
        self.closed = True
        for lookup in self.lookups.values():
            if lookup.state == 'running':
                lookup.state = 'cancelled'
            if lookup.task_handle is not None and not lookup.task_handle.done():
                lookup.task_handle.cancel()
        if self.warming is not None and not self.warming.done():
            self.warming.cancel()


_calls = {}


def open_call(session_id, user_id, room_id, dialogue, send, record):
    call = Call(session_id, user_id, room_id, dialogue, send, record)
    _calls[(user_id, room_id)] = call
    try: call.warming = asyncio.ensure_future(call.warm())
    except RuntimeError: pass   # no running loop (a test building the call by hand)
    return call


def close_call(call):
    call.close()
    if _calls.get((call.user_id, call.room_id)) is call:
        _calls.pop((call.user_id, call.room_id), None)


def for_call(user_id, room_id):
    return _calls.get((user_id, room_id))


def status(user_id, room_id):
    call = for_call(user_id, room_id)
    return [l.status() for l in call.lookups.values()][-6:] if call else []


async def run_function(name, args, user_id, room_id):
    """run_in_background / cancel_background, called by the backend of the delegation."""
    call = for_call(user_id, room_id)
    if call is None or call.closed:
        if name == 'cancel_background' or not str(args.get('task') or '').strip():
            return {'started': False, 'error': 'この通話では裏で進められない。'}
        # No sideband of this server holds the call (DAN_VOICE_SIDEBAND_OWN=0): the lookup runs here and answers as before.
        from app.services.voice_sideband import Dialogue
        async def nowhere(event): return None
        lookup = Lookup(Call('', user_id, room_id, Dialogue(), nowhere, lambda *a, **k: None), str(args['task'])[:4000], str(args.get('label') or '')[:40])
        try: return {'answer': await asyncio.wait_for(lookup._loop(), SECONDS)}
        except Exception as exc: return {'error': type(exc).__name__, 'note': '調べられなかった。分かったとは言わない。'}
    if name == 'cancel_background':
        stopped = call.cancel(str(args.get('id') or ''))
        return {'stopped': stopped, 'note': '止めた。結果は届かない。' if stopped else 'その調べものは動いていない。'}
    task = str(args.get('task') or '').strip()
    if not task:
        return {'started': False, 'error': 'task が空。'}
    label = (str(args.get('label') or '').strip() or task)[:40]
    lookup, running = call.start(task[:4000], label, str(args.get('replaces') or ''))
    others = [r for r in running if r['id'] != lookup.id]
    return {'started': True, 'id': lookup.id,
            'note': '裏で始めた。何を調べているかを一言だけ返す（例: 尼崎駅の近くでプールのあるジムを探してる）。途中で分かった事実と答えは声で本人に届くので、答えを予想して言わない。',
            **({'other_running': others, 'other_note': '訂正・条件の追加なら、その id を replaces に入れて頼み全体を渡し直す（古い方は止まる）。関係ない頼みならそのまま。'} if others else {})}
