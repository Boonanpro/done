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
QUIET_S = .7           # Dan paused this long: a stretch of speech ended
SENTENCE_S = .25       # a sentence ended and enough was said: decide sooner
CLAUSE_S = .3          # a clause ended (、) and enough was said: decide without waiting for the sentence (2026-10-27: Dan
                       # speaks one sentence for 10 seconds without a pause; the owner saw the drawing 9-12 s after the topic)
MIN_CHARS = 14         # fewer new characters than this are a backchannel, not a stretch worth a decision
CLAUSE_CHARS = 24      # a clause this long says what the topic is
USER_S = .6            # the owner's words settle (「それ図にして」 is a request to the listener too)
MODEL_TIMEOUT_S = 8.0
MAX_SCENES = 40
HOLD_S = 1.5           # after a scene was replaced, Dan's next words wait this long before another decision (2026-10-25: a
                       # flow Dan listed step by step was redrawn 4 times in 15 seconds; 6 s then, which the owner felt as
                       # the drawing lagging the talk, so 1.5 s since 2026-10-27); the owner's words are not held
HTML_MAX = 12000       # a free drawing (SVG/HTML) the model writes for the stage
NOT_ON_STAGE = ('Choice', 'Input', 'Button')   # answers and links need a chat; the stage is looked at while talking
PAGE_TIMEOUT_S = 15.0  # opening a page to photograph it for the stage
PAGE_VIEWPORT = {'width': 960, 'height': 600}

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


ICON_ALIASES = {'ticket': 'doc', 'gate': 'check', 'map': 'pin', 'location': 'pin', 'user': 'person', 'shop': 'store',
                'plane': 'globe', 'airplane': 'globe', 'bus': 'car', 'taxi': 'car', 'package': 'box', 'delivery': 'truck',
                'payment': 'card', 'cash': 'money', 'yen': 'money', 'wallet': 'money', 'email': 'mail', 'message': 'chat',
                'phone-call': 'phone', 'smartphone': 'phone', 'laptop': 'pc', 'computer': 'pc', 'cloud-upload': 'cloud',
                'ok': 'check', 'done': 'check', 'alert': 'warning', 'error': 'bad', 'time': 'clock', 'timer': 'clock',
                'date': 'calendar', 'schedule': 'calendar', 'photo': 'image', 'picture': 'image', 'settings': 'gear',
                'robot': 'bot', 'ai': 'bot', 'hospital': 'home', 'building': 'home', 'office': 'home', 'company': 'home',
                'book': 'doc', 'note': 'doc', 'list': 'doc', 'form': 'doc', 'contract': 'doc', 'receipt': 'doc',
                'tv': 'video', 'movie': 'video', 'speaker': 'mic', 'sound': 'mic', 'tag': 'flag', 'target': 'flag'}
_ICON = re.compile(r'(,\s*)?\bicon:\s*"([A-Za-z0-9_-]+)"(\s*,)?')
_icons = None


def icon_names():
    """The Flow icons the screen draws (read from its signature in the parts list)."""
    global _icons
    if _icons is None:
        found = set()
        for line in part_lines():
            if line.startswith('- Flow('):
                m = re.search(r'icon\?:\s*((?:"[a-z]+"\s*\|\s*)+"[a-z]+")', line)
                if m: found = set(re.findall(r'"([a-z]+)"', m.group(1)))
        _icons = found
    return _icons


def sanitize(program):
    """A stray icon name becomes the nearest known one, or no icon: the screen's checker refuses the whole scene for one
    unknown icon (2026-10-25: "ticket" and "gate" left the stage blank for 18 seconds and again at the end of the call)."""
    known = icon_names()
    if not known or not isinstance(program, str): return program
    out = []
    pos = 0
    for m in _ICON.finditer(program):
        name = m.group(2)
        if name in known: continue
        alias = ICON_ALIASES.get(name.lower())
        out.append(program[pos:m.start()])
        if alias in known:
            out.append((m.group(1) or '') + 'icon: "' + alias + '"' + (m.group(3) or ''))
        elif m.group(1) and m.group(3):
            out.append(m.group(3))          # a, icon: "x", b  ->  a, b
        elif m.group(1) or m.group(3):
            out.append('')                  # the only key, or first/last: the comma goes with it
        pos = m.end()
    out.append(program[pos:])
    return ''.join(out)


_TAG_OUT = re.compile(r'<\s*(script|iframe|object|embed|link|meta|base|form|input|button|textarea|select|frame|frameset|applet|audio|video|source|track)\b[^>]*>.*?(<\s*/\s*\1\s*>|$)', re.I | re.S)
_TAG_SELF = re.compile(r'<\s*/?\s*(script|iframe|object|embed|link|meta|base|form|input|button|textarea|select|frame|frameset|applet|audio|video|source|track)\b[^>]*>', re.I)
_ON_ATTR = re.compile(r'\s+on[a-z]+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', re.I)
_BAD_URL = re.compile(r'(href|src|xlink:href|action|formaction|data|poster)\s*=\s*("|\')?\s*(javascript|vbscript|data:text/html|file):[^"\'\s>]*', re.I)
_STYLE_URL = re.compile(r'(expression\s*\(|url\s*\(\s*["\']?\s*(javascript|vbscript|file):)', re.I)


def clean_html(markup):
    """A free drawing (SVG/HTML) the model wrote, with everything that could run or reach out removed: scripts, frames,
    forms, event attributes, javascript: URLs. The screen also draws it in a sandboxed frame with no scripts and its own
    origin, so this is the second wall. None when nothing drawable is left or the markup is too large."""
    if not isinstance(markup, str): return None
    text = markup.strip()
    if not text or len(text) > HTML_MAX: return None
    text = re.sub(r'^```[a-z]*\s*|\s*```$', '', text, flags=re.I).strip()
    text = _TAG_OUT.sub('', text)
    text = _TAG_SELF.sub('', text)
    text = _ON_ATTR.sub('', text)
    text = _BAD_URL.sub(r'\1=""', text)
    text = _STYLE_URL.sub('', text)
    return text if '<' in text and '>' in text else None


def safe_image(url):
    """An image the stage may show: one of Dan's files (/api/v1/files/<name>) or an https URL (no credentials)."""
    if not isinstance(url, str): return None
    url = url.strip()
    if re.fullmatch(r'/api/v1/files/[A-Za-z0-9._-]{1,200}', url): return url
    if re.fullmatch(r'https://[A-Za-z0-9.-]+(:[0-9]+)?/[^\s"\'<>\\]{0,1800}', url): return url
    return None


INSTRUCTIONS = """あなたは、本人がダン（音声アシスタント）と通話している間、本人の画面に出す「図」を決めて描く係です。声は出せません。画面だけです。
入力は、直前の会話（ユーザー＝本人、Dan＝ダン）、今の画面の札と中身、そして本人からの明示の頼み（あれば）です。
出力は JSON だけ: {"action": "keep" | "caption" | "replace", "caption": "今の話を6〜14文字で", "program": "部品のプログラム", "html": "自由な絵（SVG/HTML）", "image": "画像の URL"}
replace の時は program・html・image のどれか1つだけを入れる（内容に一番合う見せ方を選ぶ。下の「見せ方の選び方」）。

action の決め方:
- keep: 挨拶・相づち・短い返事・今の画面がまだ話に合っている時。
- caption: 話題が少し動いたが、新しく描く構造（流れ・比較・数字・手順）が無い時。札だけ替える。
- replace: ダンの説明に、人・物・流れ、比べる物、金額や件数、手順、時間の推移など「見た方が早い構造」が出た時。本人が「図にして」「画面に出して」と頼んだ時は必ず replace。
- 同じ内容を少し言い換えただけでは replace しない（画面がちらつく）。ただし、今の図に無い段階・項目・数字が足された時は replace して全部入れる。
- 入力はダンの話の途中（節の切れ目）でも届く。話の方向がもう分かるなら、文の終わりを待たずに描く（本人は図が声より遅れるのを嫌う）。まだ何の話か分からなければ keep。

見せ方の選び方（引き出しは3つ。毎回同じ型にしない）:
- program（部品）: 人・物・流れは Flow、金額・件数・時刻は Stat、比べる話は Compare、推移は Chart、順番は Steps。構造がそのまま部品に当てはまる時。
- html（自由な絵）: 部品では表しにくい物。場所の配置・部屋や機械の図解・時間の長さを帯で見せる予定表・大小や割合を面積で見せる絵・画面の見た目の下絵・一枚絵の説明図・言葉の対比のポスター風の見せ方など。SVG を書く（<svg viewBox="0 0 640 360" width="100%" …>）。背景は暗い色（#0a0a0a 系）で、文字は白か明るい色、文字の大きさは 18px 以上、要素は10個まで。script・外部の読み込み・リンク・フォームは書かない（消される）。中身は 12000 文字まで。
- image（画像）: 会話に実在する画像の URL（/api/v1/files/… か https://）を見せる時だけ。URL を作らない。

描き方の決まり（program は OpenUI Lang。`root = Part(...)` に加え、`name = Part(...)` の行を書いて root から名前で参照できる。引数は位置で渡し、文字は二重引用符、省略できる引数は後ろから省く。name: value の書き方はしない）:
- 図は、声を聞いていない人が見ても何の話か分かる物にする。Heading の text は「この図が言っていること」を1文で（例: 「予約から乗るまでは4段階」「東京まで約2時間半・14,920円」）。Heading の sub に、図の読み方か要点を1行足す。
- 文字だけの表・箇条書きにしない。人・物・流れは Flow（アイコン＋矢印の図）、今どこかは Flow の tone "now"、金額・件数・時刻は Stat で大きく1つ、比べる話は Compare、推移は Chart、順番は Steps。
- Flow の箱の label は、それが何かが分かる言葉（「公開鍵」ではなく「アプリの鍵」、「表」ではなく「会員の表」）。箱の sub に役割や状態を短く。矢印の label は「持つ」「読める」のような動き（動詞）。名詞を3つ並べただけの Flow は描かない。
- 数字が出た話は、その数字を Stat にして何の数字かを label に書き、note に条件（いつ・どの区間・税込かなど）を書く。
- Flow の icon は一覧にある名前だけ（ticket・gate・map は無い。きっぷは doc、改札は check、場所は pin）。無い名前を書くと図ごと出ない。
- replace の時は、Heading も新しい図に合わせて書き直す（前の画面の見出しを残さない。料金の見出しの下に流れの図、のような食い違いを作らない）。
- ダンが口で挙げた段階・項目は、図にも全部入れる（「予約→駅→改札→ホーム→乗車→到着」と言ったら6個全部。6個を超える時だけまとめる）。
- 画面は1枚で、通話しながら一目で分かる量にする: 部品は6個まで、Flow の箱は6個まで、箱の文字は8文字まで、Stat は3個まで。
- Choice・Input・Button は使わない。Image は会話に実在する URL（/api/v1/files/… か https://）がある時だけ。URL を作らない。
- 事実は会話に出た物だけ。数字・名前を補わない。分からない所は書かない。
- 引数は必ず位置で書く。tone: "good" のような name: value は {} の中（箱や項目）だけで使え、部品の引数には書けない（Stat("納付額", 36000, "円", "納付済み", "good") のように、途中の省く引数は "" で埋める）。
- caption は常に返す（keep でも、今の話を表す札。前と同じでよい）。

使える部品（? は省略可。Part は部品のどれか）:
{parts}

例:
{"action": "replace", "caption": "DB の守りの仕組み", "program": "root = Column([Heading(\\"DB は許した表しか読めない\\", \\"アプリの鍵では会員の表に届かない\\"), Flow([{id: \\"app\\", label: \\"アプリ\\", icon: \\"phone\\", sub: \\"みきさんの手元\\"}, {id: \\"api\\", label: \\"ダンの鍵\\", icon: \\"key\\", sub: \\"本人の印つき\\", tone: \\"now\\"}, {id: \\"db\\", label: \\"会員の表\\", icon: \\"database\\", sub: \\"守られている\\", tone: \\"good\\"}], [{from: \\"app\\", to: \\"api\\", label: \\"渡す\\"}, {from: \\"api\\", to: \\"db\\", label: \\"読める\\"}])])"}
{"action": "replace", "caption": "東京までの料金と時間", "program": "root = Column([Heading(\\"東京まで約2時間半・14,920円\\", \\"のぞみ指定席、新大阪から\\"), Row([Stat(\\"料金\\", 14920, \\"円\\", \\"指定席・片道\\"), Stat(\\"所要時間\\", \\"2時間30分\\", \\"\\", \\"新大阪→品川\\")])])"}
{"action": "replace", "caption": "リビングの配置", "html": "<svg viewBox=\\"0 0 640 360\\" width=\\"100%\\" xmlns=\\"http://www.w3.org/2000/svg\\"><rect width=\\"640\\" height=\\"360\\" fill=\\"#0a0a0a\\"/><text x=\\"24\\" y=\\"40\\" fill=\\"#fff\\" font-size=\\"24\\">窓際に机、ソファは入口側</text><rect x=\\"40\\" y=\\"70\\" width=\\"560\\" height=\\"250\\" fill=\\"none\\" stroke=\\"#666\\" stroke-width=\\"2\\"/><rect x=\\"60\\" y=\\"90\\" width=\\"200\\" height=\\"80\\" fill=\\"#2b6cb0\\"/><text x=\\"160\\" y=\\"138\\" fill=\\"#fff\\" font-size=\\"20\\" text-anchor=\\"middle\\">机（窓際）</text><rect x=\\"360\\" y=\\"220\\" width=\\"220\\" height=\\"80\\" fill=\\"#b7791f\\"/><text x=\\"470\\" y=\\"268\\" fill=\\"#fff\\" font-size=\\"20\\" text-anchor=\\"middle\\">ソファ（入口側）</text></svg>"}
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


def decision_input(turns, caption, program, request=None, html=None, image=None):
    talk = chr(10).join(('ユーザー' if t['role'] == 'user' else 'Dan') + ': ' + t['text'].strip()[:700] for t in turns if t['text'].strip())
    shown = program or (('（自由な絵）' + chr(10) + html[:1500]) if html else '') or (('（画像）' + image) if image else '') or '（まだ無い）'
    text = '直前の会話（新しい物が下）:' + chr(10) + talk + chr(10) + chr(10) + '今の画面の札: ' + (caption or '（まだ無い）') + chr(10) + '今の画面の中身: ' + shown
    if request: text += chr(10) + chr(10) + '本人からの明示の頼み（必ず replace で描く）: ' + request
    return text


class Stage:
    """One call's stage: the listener, the file the screen reads, and the scenes shown (for the record after the call).

    A scene is one of three things: a parts program (the chat's parts), a free drawing (SVG/HTML the model wrote,
    cleaned here, drawn by the screen in a sandboxed frame) or an image (one of Dan's files or an https URL, including a
    photograph of a page taken for the owner: show_page)."""

    def __init__(self, room_id, session_id, dialogue, record, ask=None, user_id=None):
        self.room_id, self.session_id, self.dialogue, self.record, self.user_id = room_id, session_id, dialogue, record, user_id
        self.ask = ask or ask_model
        # The version counts on from the room's previous call: the screen long-polls for a version above the last one
        # it saw, so a new call restarting at 1 never reached it (2026-10-25 3rd test call: 5 scenes drawn, none shown).
        self.version = int((read_state(room_id) or {}).get('version') or 0)
        self.caption, self.program, self.html, self.image, self.page_url, self.at = '', '', '', '', '', None
        self.scenes = []
        self.pending_chars, self.user_pending = 0, False
        self._timer = None
        self._decisions = 0          # decisions started
        self._applied = 0            # the newest decision whose answer reached the screen
        self._last_replace = -1e9    # when the scene was last replaced (monotonic)
        self._tasks = set()
        self._names = None
        _stages[room_id] = self
        self.write(active=True)

    # -- what the screen reads --------------------------------------------------------------------------------
    def state(self, active=True):
        return {'room_id': self.room_id, 'session_id': self.session_id, 'version': self.version, 'caption': self.caption,
                'program': self.program, 'html': self.html, 'image': self.image, 'page_url': self.page_url, 'at': self.at,
                'active': active, 'scenes': len(self.scenes)}

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
        """A transcript delta arrived. Dan's words are decided on at a clause end, a sentence end or a pause; the owner's
        words a moment after they settle (a request to draw is theirs), and Dan's first words do not push that moment
        back (2026-10-26: the owner's question set a decision, Dan's answer kept rescheduling it, so the drawing waited
        for the end of Dan's sentence)."""
        if not delta or not delta.strip(): return
        if role == 'assistant':
            self.pending_chars += len(delta.strip())
            if self.user_pending and self._timer is not None: return
            if re.search(r'[。！？!?]\s*$', delta) and self.pending_chars >= MIN_CHARS * 2: wait = SENTENCE_S
            elif '、' in delta and self.pending_chars >= CLAUSE_CHARS: wait = CLAUSE_S
            else: wait = QUIET_S
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
        held = HOLD_S - (time.monotonic() - self._last_replace)
        if held > 0 and not self.user_pending:
            self._schedule(held)   # the words so far are decided on together, after the hold
            return
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
            data, usage = await asyncio.wait_for(self.ask(instructions(), decision_input(turns, self.caption, self.program, request, self.html, self.image)), MODEL_TIMEOUT_S)
        except Exception as exc:
            self.record('stage_failed', error_type=type(exc).__name__, detail=str(exc)[:160], elapsed_ms=round((time.monotonic() - started) * 1000))
            return None
        elapsed = round((time.monotonic() - started) * 1000)
        action = str(data.get('action') or 'keep')
        caption = str(data.get('caption') or '').strip()[:40]
        program = sanitize(data.get('program')) if isinstance(data.get('program'), str) else None
        html = clean_html(data.get('html')) if data.get('html') else None
        image = safe_image(data.get('image')) if data.get('image') else None
        drawable = {'program': program.strip()} if well_formed(program, self._known()) else {'html': html} if html else {'image': image} if image else None
        if request and action != 'replace' and drawable: action = 'replace'
        if mine < self._applied:
            self.record('stage_stale', action=action, elapsed_ms=elapsed)
            return None
        self._applied = mine
        if action == 'replace':
            if not drawable:
                self.record('stage_rejected', elapsed_ms=elapsed, chars=len(str(program or html or image or '')), **usage)
                if caption and caption != self.caption: self._apply(caption)
                return 'rejected'
            self._apply(caption or self.caption, **drawable)
            self._last_replace = time.monotonic()
            kind = next(iter(drawable))
            self.record('stage_scene', elapsed_ms=elapsed, kind=kind, chars=len(drawable[kind]), version=self.version, **usage)
            return 'replace'
        if action == 'caption' and caption and caption != self.caption:
            self._apply(caption)
            self.record('stage_caption', elapsed_ms=elapsed, **usage)
            return 'caption'
        self.record('stage_keep', elapsed_ms=elapsed, **usage)
        return 'keep'

    def _known(self):
        if self._names is None: self._names = part_names()
        return self._names

    def _apply(self, caption, program=None, html=None, image=None, page_url=''):
        """A new version for the screen: a caption alone, or a new scene (exactly one of program / html / image)."""
        self.version += 1
        self.caption = caption
        self.at = datetime.now(timezone.utc).isoformat()
        if program is not None or html is not None or image is not None:
            self.program, self.html, self.image, self.page_url = program or '', html or '', image or '', page_url or ''
            self.scenes.append({'version': self.version, 'at': self.at, 'caption': caption, 'program': self.program,
                                'html': self.html, 'image': self.image, 'page_url': self.page_url})
            del self.scenes[:-MAX_SCENES]
        self.write(active=True)

    async def show(self, what):
        """The owner asked (through the call's backend) for a drawing: decided now, with the request."""
        if self._timer is not None: self._timer.cancel(); self._timer = None
        result = await self.decide(request=str(what or '')[:400])
        return {'shown': result == 'replace', 'caption': self.caption, 'reason': None if result == 'replace' else (result or 'failed')}

    # -- a real page on the stage -----------------------------------------------------------------------------
    async def show_page(self, url='', artifact='', note=''):
        """Open a page in a browser of this server and put its photograph on the stage: a URL, or one of the owner's
        artifacts by name (the owner on 2026-10-27: the stage must show real screens, not only drawings)."""
        started = time.monotonic()
        target, title = await resolve_page(self.user_id, url, artifact)
        if not target:
            self.record('stage_page_failed', reason='not_found', elapsed_ms=round((time.monotonic() - started) * 1000))
            return {'shown': False, 'reason': f'「{artifact or url}」という成果物やページが見つからなかった。'}
        try:
            path = await capture_page(target, self.user_id, self.room_id)
        except Exception as exc:
            self.record('stage_page_failed', reason=type(exc).__name__, detail=str(exc)[:160], elapsed_ms=round((time.monotonic() - started) * 1000))
            return {'shown': False, 'reason': f'ページを開けなかった（{type(exc).__name__}）。'}
        caption = (str(note or '').strip() or title or target)[:40]
        self._apply(caption, image=path, page_url=target)
        self._last_replace = time.monotonic()
        self.record('stage_page', elapsed_ms=round((time.monotonic() - started) * 1000), version=self.version)
        return {'shown': True, 'caption': caption, 'url': target, 'image': path}

    # -- the end ----------------------------------------------------------------------------------------------
    def close(self):
        if self._timer is not None: self._timer.cancel(); self._timer = None
        for task in list(self._tasks): task.cancel()
        self.write(active=False)
        if _stages.get(self.room_id) is self: _stages.pop(self.room_id, None)

    def summary(self, zone='Asia/Tokyo'):
        """The one chat message that records what the call showed, scene by scene, as the parts themselves (a free
        drawing as its markup, a page as its photograph)."""
        if not self.scenes: return ''
        from zoneinfo import ZoneInfo
        local = ZoneInfo(zone)
        lines = [f'🖼 通話中に出した画面（{len(self.scenes)}枚）']
        for scene in self.scenes:
            when = datetime.fromisoformat(scene['at']).astimezone(local).strftime('%H:%M')
            lines.append('')
            lines.append(f'**{when} {scene["caption"]}**' if scene['caption'] else f'**{when}**')
            if scene.get('program'):
                lines.append('```openui-lang'); lines.append(scene['program']); lines.append('```')
            elif scene.get('html'):
                lines.append('```html'); lines.append(scene['html']); lines.append('```')
            elif scene.get('image'):
                lines.append(f'[添付画像: {scene["image"]}]')
                if scene.get('page_url'): lines.append(scene['page_url'])
        return chr(10).join(lines)


# -- pages for the stage -------------------------------------------------------------------------------------------

def screens_base():
    """Where the owner's screens are served from (the artifacts' pages): the public site when configured, else the local
    production build."""
    from app.config import settings
    return (os.environ.get('DAN_PUBLIC_BASE_URL') or settings.FRONTEND_URL or 'http://127.0.0.1:3000').rstrip('/')


async def resolve_page(user_id, url='', artifact=''):
    """The URL to photograph and a short title: an https URL as given, a path on this site under the screens' base, or
    the owner's artifact whose title or slug matches the words (the longest common match wins)."""
    url = str(url or '').strip()
    if url.startswith(('http://', 'https://')): return url, ''
    if url.startswith('/'): return screens_base() + url, ''
    words = str(artifact or url or '').strip()
    if not words or not user_id: return None, ''
    try:
        from app.services.chat_artifact_service import ChatArtifactService
        rows = await ChatArtifactService().list(user_id, limit=200)
    except Exception as exc:
        logger.info('artifacts not listed for the stage: %s', type(exc).__name__)
        rows = []
    lowered = words.lower().replace(' ', '').replace('　', '')
    best, score = None, 0
    for row in rows:
        for key in ('label', 'title', 'slug', 'name'):
            value = str(row.get(key) or '').lower().replace(' ', '')
            if not value: continue
            s = len(value) if value in lowered or lowered in value else _overlap(value, lowered)
            if s > score: best, score = row, s
    if best is None or score < 2: return None, ''
    path = best.get('preview_url') or ('/artifacts/' + str(best.get('slug') or ''))
    return screens_base() + path, str(best.get('label') or best.get('title') or best.get('slug') or '')


def _overlap(a, b):
    """The longest run of characters the two strings share (2 or more)."""
    longest = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]: k += 1
            if k > longest: longest = k
    return longest


async def capture_page(url, user_id, room_id):
    """Photograph a page in a headless browser of this server and save it as one of Dan's files (/api/v1/files/…).
    Pages of this site get the owner's token (a short-lived one) in localStorage so signed-in screens show."""
    from playwright.async_api import async_playwright
    from app.api.file_routes import UPLOAD_DIR
    from urllib.parse import urlparse
    token = ''
    if user_id and urlparse(url).netloc == urlparse(screens_base()).netloc:
        try:
            from datetime import timedelta
            from app.services.auth_service import create_access_token
            token = create_access_token(str(user_id), '', timedelta(minutes=10))
        except Exception: token = ''
    name = f'stage-{_name(room_id)[:24]}-{int(time.time() * 1000)}.png'
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(viewport=PAGE_VIEWPORT, locale='ja-JP', timezone_id='Asia/Tokyo', color_scheme='dark')
            if token: await context.add_init_script(f"localStorage.setItem('done-token', {json.dumps(token)});")
            page = await context.new_page()
            await page.goto(url, wait_until='load', timeout=PAGE_TIMEOUT_S * 1000)
            await page.wait_for_timeout(900)
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(UPLOAD_DIR / name))
        finally:
            await browser.close()
    return '/api/v1/files/' + name
