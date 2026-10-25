"""The call's stage: what the owner sees while Dan talks.

While a call runs, Dan's words reach this server as transcript deltas (voice_sideband). A listener here reads them and,
at each pause in Dan's speech, asks a fast text model what the screen should show: keep the current scene, change only
the caption (「今の話: …」), or draw a new scene. A scene is an answer-shapes program (the ```openui-lang parts the chat
draws: Flow diagrams, big numbers, tables, charts), so the screen draws it in milliseconds; writing it is what costs
time (measured by the tests on the sideband log: stage_scene elapsed_ms).

Why not the speech model: gpt-live-1 handles no images or structured output and talks on while a backend tool works, so a
drawing asked of it arrives late and after the words. Why not Jev's decisions: they choose among given answers and
write no text, and a scene is text (the owner asked on 2026-10-25).

The stage is one JSON file per room (next to voice_calls' files) so the screen's poll (voicelog_routes GET /stage) can be
served by any process; the scenes shown are also kept here for the one chat message that records them after the call.
DAN_VOICE_STAGE=0 turns the listener off. DAN_VOICE_STAGE_MODEL picks the model. Measured on 2026-10-25 with
scripts/check_voice_stage_latency.py (10 decisions over three explanations): gpt-5.4-mini with no reasoning 1.2 s median,
1.5 s max, every scene drawable; gpt-5.4-nano 1.6 s / 2.5 s; deepseek-flash 4.6 s / 6.1 s (one scene with a named
argument); gpt-5-nano never drew. The default is gpt-5.4-mini.
"""
import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from app.services.voice_calls import ROOT, _name

logger = logging.getLogger(__name__)

MODEL = os.environ.get('DAN_VOICE_STAGE_MODEL', 'gpt-5.4-mini')
REASONING = os.environ.get('DAN_VOICE_STAGE_REASONING', 'none')   # gpt-5 class only ('minimal' is refused by gpt-5.4)
QUIET_S = .9           # Dan paused this long: a stretch of speech ended
SENTENCE_S = .35       # a sentence ended and enough was said: decide sooner
MIN_CHARS = 14         # fewer new characters than this are a backchannel, not a stretch worth a decision
USER_S = 1.0           # the owner's words settle (「それ図にして」 is a request to the listener too)
MODEL_TIMEOUT_S = 8.0
MAX_SCENES = 40
NOT_ON_STAGE = ('Choice', 'Input', 'Button')   # answers and links need a chat; the stage is looked at while talking

_stages = {}   # room_id -> Stage, for the backend tool show_on_stage (voice_responses)


def enabled():
    return os.environ.get('DAN_VOICE_STAGE', '1') != '0'


def stage_file(room_id):
    return ROOT / (_name(room_id) + '.stage.json')


def read_state(room_id):
    """The stage as the screen reads it: {} when the room has no stage file."""
    try:
        return json.loads(stage_file(room_id).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def for_room(room_id):
    return _stages.get(room_id)


def part_lines():
    """The part signatures the chat screen draws (generated from the frontend's definitions, chat_shapes_prompt.md),
    without the parts that need a chat to answer or follow (Choice, Input, Button)."""
    from app.agent.chat_shapes import chat_shapes_section
    lines = [l for l in chat_shapes_section().splitlines() if l.startswith('- ') and '(' in l]
    return [l for l in lines if l[2:].split('(')[0] not in NOT_ON_STAGE]


def part_names():
    return {l[2:].split('(')[0] for l in part_lines()}


INSTRUCTIONS = """あなたは、本人がダン（音声アシスタント）と通話している間、本人の画面に出す「図」を決めて描く係です。声は出せません。画面だけです。
入力は、直前の会話（ユーザー＝本人、Dan＝ダン）、今の画面の札と中身、そして本人からの明示の頼み（あれば）です。
出力は JSON だけ: {"action": "keep" | "caption" | "replace", "caption": "今の話を6〜14文字で", "program": "部品のプログラム（replace の時だけ）"}

action の決め方:
- keep: 挨拶・相づち・短い返事・今の画面がまだ話に合っている時。
- caption: 話題が少し動いたが、新しく描く構造（流れ・比較・数字・手順）が無い時。札だけ替える。
- replace: ダンの説明に、人・物・流れ、比べる物、金額や件数、手順、時間の推移など「見た方が早い構造」が出た時。本人が「図にして」「画面に出して」と頼んだ時は必ず replace。
- 同じ内容を少し言い換えただけでは replace しない（画面がちらつく）。

描き方の決まり（program は OpenUI Lang。`root = Part(...)` に加え、`name = Part(...)` の行を書いて root から名前で参照できる。引数は位置で渡し、文字は二重引用符、省略できる引数は後ろから省く。name: value の書き方はしない）:
- 文字だけの表・箇条書きにしない。人・物・流れは Flow（アイコン＋矢印の図）、今どこかは Flow の tone "now"、金額・件数・時刻は Stat で大きく1つ、比べる話は Compare、推移は Chart、順番は Steps。見出しは Heading で1行。
- 画面は1枚で、通話しながら一目で分かる量にする: 部品は6個まで、Flow の箱は6個まで、箱の文字は8文字まで、Stat は3個まで。
- Choice・Input・Button は使わない。Image は会話に実在する URL（/api/v1/files/… か https://）がある時だけ。URL を作らない。
- 事実は会話に出た物だけ。数字・名前を補わない。分からない所は書かない。
- 引数は必ず位置で書く。tone: "good" のような name: value は {} の中（箱や項目）だけで使え、部品の引数には書けない（Stat("納付額", 36000, "円", "納付済み", "good") のように、途中の省く引数は "" で埋める）。
- caption は常に返す（keep でも、今の話を表す札。前と同じでよい）。

使える部品（? は省略可。Part は部品のどれか）:
{parts}

例:
{"action": "replace", "caption": "DB の守りの仕組み", "program": "root = Column([Heading(\\"誰が何を読めるか\\"), Flow([{id: \\"app\\", label: \\"アプリ\\", icon: \\"phone\\"}, {id: \\"api\\", label: \\"ダンの鍵\\", icon: \\"key\\", tone: \\"now\\"}, {id: \\"db\\", label: \\"DB\\", icon: \\"database\\"}], [{from: \\"app\\", to: \\"api\\", label: \\"本人の印\\"}, {from: \\"api\\", to: \\"db\\", label: \\"許可した表だけ\\"}])])"}
"""


def instructions():
    return INSTRUCTIONS.replace('{parts}', chr(10).join(part_lines()))


_WORD = re.compile(r'\b([A-Z][A-Za-z]+)\(')


def well_formed(program, names=None):
    """A program the screen can be expected to draw: `root =`, only known parts, none of the chat-only parts, balanced
    brackets outside strings, a sane size. The screen validates fully (checkShapeProgram) and keeps its last scene
    when a program fails there; this check stops the obvious failures before they travel."""
    if not isinstance(program, str) or not program.strip() or len(program) > 6000: return False
    if not re.search(r'^\s*root\s*=', program, re.M): return False
    names = names if names is not None else part_names()
    used = set(_WORD.findall(program))
    if not used or not used <= names or used & set(NOT_ON_STAGE): return False
    depth, quote, escape, word = [], None, False, ''
    pairs = {'(': ')', '[': ']', '{': '}'}
    for ch in program:
        if quote:
            if escape: escape = False
            elif ch == '\\': escape = True
            elif ch == quote: quote = None
            continue
        if ch in '"\'': quote = ch; word = ''
        elif ch in pairs: depth.append(pairs[ch]); word = ''
        elif ch in ')]}':
            if not depth or depth.pop() != ch: return False
            word = ''
        elif ch == ':':
            # `name: value` is only an object's key (inside {}); as an argument (inside () or []) it is a named argument,
            # which the screen's reader does not know (deepseek wrote Stat("Done 側", 59, "表", tone: "good"), 2026-10-25)
            if word and depth and depth[-1] != '}': return False
            word = ''
        elif ch.isalnum() or ch == '_': word += ch
        elif not ch.isspace(): word = ''
    return not depth and quote is None


def _client():
    from openai import AsyncOpenAI
    from app.services import inbox
    inbox._env()   # the keys from .env (the process's environment does not carry them)
    if MODEL.startswith(('gpt-', 'o')):
        from app.config import settings
        return AsyncOpenAI(api_key=settings.OPENAI_API_KEY or os.environ.get('OPENAI_API_KEY'), timeout=MODEL_TIMEOUT_S, max_retries=0)
    base = os.environ.get('DAN_CHAT_BASE_URL') or ('https://api.deepseek.com' if MODEL.startswith('deepseek') else None)
    key = os.environ.get('DAN_CHAT_API_KEY') or os.environ.get('DEEPSEEK_API_KEY')
    return AsyncOpenAI(api_key=key, base_url=base, timeout=MODEL_TIMEOUT_S, max_retries=0)


async def ask_model(system, user):
    """One decision from the model: the parsed JSON object (or {} when it is not one)."""
    client = _client()
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
    if MODEL.startswith(('gpt-5', 'o')):   # reasoning models: no temperature, the smallest reasoning, the newer token limit
        response = await client.chat.completions.create(model=MODEL, max_completion_tokens=1600, reasoning_effort=REASONING,
                                                        response_format={'type': 'json_object'}, messages=messages)
    else:
        response = await client.chat.completions.create(model=MODEL, temperature=0.2, max_tokens=1200,
                                                        response_format={'type': 'json_object'}, messages=messages)
    text = (response.choices[0].message.content or '') if response.choices else ''
    try:
        found = re.search(r'\{.*\}', text, re.S)
        data = json.loads(found.group(0)) if found else {}
    except ValueError:
        data = {}
    usage = getattr(response, 'usage', None)
    return (data if isinstance(data, dict) else {}), {'input_tokens': getattr(usage, 'prompt_tokens', 0) or 0, 'output_tokens': getattr(usage, 'completion_tokens', 0) or 0}


def decision_input(turns, caption, program, request=None):
    talk = chr(10).join(('ユーザー' if t['role'] == 'user' else 'Dan') + ': ' + t['text'].strip()[:700] for t in turns if t['text'].strip())
    text = '直前の会話（新しい物が下）:' + chr(10) + talk + chr(10) + chr(10) + '今の画面の札: ' + (caption or '（まだ無い）') + chr(10) + '今の画面の中身: ' + (program or '（まだ無い）')
    if request: text += chr(10) + chr(10) + '本人からの明示の頼み（必ず replace で描く）: ' + request
    return text


class Stage:
    """One call's stage: the listener, the file the screen reads, and the scenes shown (for the record after the call)."""

    def __init__(self, room_id, session_id, dialogue, record, ask=None):
        self.room_id, self.session_id, self.dialogue, self.record = room_id, session_id, dialogue, record
        self.ask = ask or ask_model
        self.version, self.caption, self.program, self.at = 0, '', '', None
        self.scenes = []
        self.pending_chars, self.user_pending = 0, False
        self._timer = None
        self._decisions = 0          # decisions started
        self._applied = 0            # the newest decision whose answer reached the screen
        self._tasks = set()
        self._names = None
        _stages[room_id] = self
        self.write(active=True)

    # -- what the screen reads --------------------------------------------------------------------------------
    def state(self, active=True):
        return {'room_id': self.room_id, 'session_id': self.session_id, 'version': self.version, 'caption': self.caption,
                'program': self.program, 'at': self.at, 'active': active, 'scenes': len(self.scenes)}

    def write(self, active=True):
        try:
            ROOT.mkdir(parents=True, exist_ok=True)
            path = stage_file(self.room_id)
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.state(active), ensure_ascii=False), encoding='utf-8')
            os.replace(tmp, path)
        except OSError:
            logger.exception('stage not written room=%s', self.room_id)

    # -- the listener -----------------------------------------------------------------------------------------
    def heard(self, role, delta):
        """A transcript delta arrived. Dan's words are decided on at a pause or a sentence end; the owner's words a
        moment after they settle (a request to draw is theirs)."""
        if not delta or not delta.strip(): return
        if role == 'assistant':
            self.pending_chars += len(delta.strip())
            wait = SENTENCE_S if re.search(r'[。！？!?]\s*$', delta) and self.pending_chars >= MIN_CHARS * 2 else QUIET_S
        else:
            self.user_pending = True
            wait = USER_S
        self._schedule(wait)

    def _schedule(self, wait):
        if self._timer is not None: self._timer.cancel()
        loop = asyncio.get_running_loop()
        self._timer = loop.create_task(self._after(wait))

    async def _after(self, wait):
        await asyncio.sleep(wait)
        self._timer = None
        if self.pending_chars < MIN_CHARS and not self.user_pending: return
        task = asyncio.ensure_future(self.decide())
        self._tasks.add(task); task.add_done_callback(self._tasks.discard)

    async def decide(self, request=None):
        """Ask the model what the screen should show now and apply it, unless a newer decision was applied meanwhile
        (the newest words win; an older answer arriving late is dropped)."""
        self.pending_chars, self.user_pending = 0, False
        self._decisions += 1
        mine = self._decisions
        turns = self.dialogue.recent()[-8:] if self.dialogue is not None else []
        if not turns and not request: return None
        started = time.monotonic()
        try:
            data, usage = await asyncio.wait_for(self.ask(instructions(), decision_input(turns, self.caption, self.program, request)), MODEL_TIMEOUT_S)
        except Exception as exc:
            self.record('stage_failed', error_type=type(exc).__name__, detail=str(exc)[:160], elapsed_ms=round((time.monotonic() - started) * 1000))
            return None
        elapsed = round((time.monotonic() - started) * 1000)
        action = str(data.get('action') or 'keep')
        caption = str(data.get('caption') or '').strip()[:40]
        program = data.get('program')
        if request and action != 'replace' and well_formed(program, self._known()): action = 'replace'
        if mine < self._applied:
            self.record('stage_stale', action=action, elapsed_ms=elapsed)
            return None
        self._applied = mine
        if action == 'replace':
            if not well_formed(program, self._known()):
                self.record('stage_rejected', elapsed_ms=elapsed, chars=len(str(program or '')), **usage)
                if caption and caption != self.caption: self._apply(caption, None)
                return 'rejected'
            self._apply(caption or self.caption, program.strip())
            self.record('stage_scene', elapsed_ms=elapsed, chars=len(program), version=self.version, **usage)
            return 'replace'
        if action == 'caption' and caption and caption != self.caption:
            self._apply(caption, None)
            self.record('stage_caption', elapsed_ms=elapsed, **usage)
            return 'caption'
        self.record('stage_keep', elapsed_ms=elapsed, **usage)
        return 'keep'

    def _known(self):
        if self._names is None: self._names = part_names()
        return self._names

    def _apply(self, caption, program):
        self.version += 1
        self.caption = caption
        self.at = datetime.now(timezone.utc).isoformat()
        if program is not None:
            self.program = program
            self.scenes.append({'version': self.version, 'at': self.at, 'caption': caption, 'program': program})
            del self.scenes[:-MAX_SCENES]
        self.write(active=True)

    async def show(self, what):
        """The owner asked (through the call's backend) for a drawing: decided now, with the request."""
        if self._timer is not None: self._timer.cancel(); self._timer = None
        result = await self.decide(request=str(what or '')[:400])
        return {'shown': result == 'replace', 'caption': self.caption, 'reason': None if result == 'replace' else (result or 'failed')}

    # -- the end ----------------------------------------------------------------------------------------------
    def close(self):
        if self._timer is not None: self._timer.cancel(); self._timer = None
        for task in list(self._tasks): task.cancel()
        self.write(active=False)
        if _stages.get(self.room_id) is self: _stages.pop(self.room_id, None)

    def summary(self, zone='Asia/Tokyo'):
        """The one chat message that records what the call showed, scene by scene, as the parts themselves."""
        if not self.scenes: return ''
        from zoneinfo import ZoneInfo
        local = ZoneInfo(zone)
        lines = [f'🖼 通話中に出した画面（{len(self.scenes)}枚）']
        for scene in self.scenes:
            when = datetime.fromisoformat(scene['at']).astimezone(local).strftime('%H:%M')
            lines.append('')
            lines.append(f'**{when} {scene["caption"]}**' if scene['caption'] else f'**{when}**')
            lines.append('```openui-lang')
            lines.append(scene['program'])
            lines.append('```')
        return chr(10).join(lines)
