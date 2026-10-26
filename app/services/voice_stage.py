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
CLAUSE_CHARS = 16      # a clause this long says what the topic is
USER_S = .6            # the owner's words settle (「それ図にして」 is a request to the listener too)
MODEL_TIMEOUT_S = 8.0
MAX_SCENES = 40
HOLD_S = 1.5           # after a scene was replaced, Dan's next words wait this long before another decision (2026-10-25: a
                       # flow Dan listed step by step was redrawn 4 times in 15 seconds; 6 s then, which the owner felt as
                       # the drawing lagging the talk, so 1.5 s since 2026-10-27); the owner's words are not held
FLIP_HOLD_S = 12.0     # a replace that changes to a different kind of scene (flow -> numbers) this soon after the last one,
                       # with no request from the owner and no new words of theirs, only changes the caption (2026-10-27 1st test call: the model
                       # alternated between the journey's flow and the fare 6 times in 60 s while Dan said nothing new)
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


# -- a message draft on the stage (2026-10-27: 「○○さんにメッセージ送って」 → the draft is shown, revised by voice, sent by voice) --
# What the owner says that means "send it" / "not yet". The server reads the call's transcript itself: the model that
# calls send is not trusted to have heard an approval (the owner: 「送って」「いいよ」以外の言葉では送らない).
APPROVAL = re.compile(r'(いいよ|いいです|いいっす|良いよ|よいよ|送って|送信して|送っちゃって|送ろう|送る|オッケー|オーケー|おっけ|ok|okay|お願い|大丈夫|それで|はい|うん|ええ|どうぞ|ゴー|go|頼む|よろしく|やって|進めて|問題ない|承認|了解)', re.I)
HESITATION = re.compile(r'(待って|まって|まだ|やめ|止め|とめ|ちょっと|うーん|う〜ん|えーと|えっと|直し|なおし|変え|かえ|違う|ちがう|なし|ダメ|だめ|送らない|やっぱ|考え|後で|あとで|どうしよう|どうかな|かな[。？?]?$|微妙|保留|一旦|いったん|見せて|読んで|もう一回|もう一度|\?|？)', re.I)
FLOW_S = 1.0           # the owner's words about the draft on the stage settle this long before the server acts on them
FLOW_INSTRUCTIONS = """通話中、本人の画面にはダンが作ったメッセージの下書き（送信案: 宛先・件名・本文）が出ています。本人の直前の言葉が、その下書きに対して何を求めているかを判定します。出力は JSON だけ:
{"intent": "revise" | "send" | "approve" | "stop" | "discard" | "other", "body": "直した本文全体（revise の時だけ）", "subject": "直した件名（件名を変える時だけ）", "to_name": "直した宛名（宛名を変える時だけ）"}
- revise: 文面・件名・宛名を変える頼み（「もっと短く」「最後に日程を足して」「2行目を柔らかく」「宛名を田中様に」）。body には直した後の本文全体を書く。頼まれた所だけ変え、ほかの行は一字も変えない。本人が言った内容（日時・名前・数字）だけを使い、補わない。
- send: 送ってほしいという頼み（「送って」「送信して」「それで出して」「送っちゃって」）。
- approve: ダンが宛先と要点を読み上げて「送っていいですか」と聞いた後の、承認の返事（「いいよ」「OK」「はい」「お願い」「それで」）。
- stop: 待ってほしい・保留（「ちょっと待って」「まだ」「うーん」「もう一回読んで」）。
- discard: 送らない・取り下げ（「やめて」「送らないで」「消して」「なしで」）。
- other: 下書きと関係ない話、挨拶、相づち、ダンへの質問。
迷う時は other か stop（送る側に倒さない）。"""


def flow_input(card, dan_words, owner_words):
    return ('今の下書き:' + chr(10) + card_text(card) + chr(10) + chr(10) + 'ダンの直前の言葉: ' + (' '.join(str(dan_words or '').split())[:400] or '（無し）')
            + chr(10) + '本人の新しい言葉: ' + ' '.join(str(owner_words or '').split())[:600])


CARD_CHANNELS_SPOKEN = {'email': 'メール', 'instagram_dm': 'Instagram の DM', 'instagram_comment': 'Instagram のコメント', 'collab': '窓口のチャット',
                        'line': 'LINE', 'sms': 'SMS', 'web_form': 'フォーム', 'chatwork': 'Chatwork', 'slack': 'Slack', 'x_dm': 'X の DM'}


async def _silent(text):
    """Where no voice is attached (tests, a stage without a call): the result is only recorded."""
    return None


def _message_service():
    from app.services.outbound_message_service import OutboundMessageService
    return OutboundMessageService()


def card_of(row):
    """The stage's view of a proposal row (dan_proposals): what the screen draws and the record keeps."""
    ad = row.get('action_data') or {}
    return {'proposal_id': str(row.get('id') or ''), 'status': str(row.get('status') or 'pending'), 'channel': str(ad.get('channel') or 'other'),
            'to': str(ad.get('to') or ''), 'to_name': str(ad.get('to_name') or ''), 'subject': str(ad.get('subject') or ''),
            'body': str(row.get('content') or ''), 'intent': str(ad.get('intent') or ''), 'revision': int(ad.get('revision') or 1),
            'sent_at': str(ad.get('sent_at') or ''), 'sendable': str(ad.get('channel') or '') in SENDABLE}


SENDABLE = {'email', 'instagram_dm', 'instagram_comment', 'collab'}   # app.services.outbound_message_service.SERVER_SENDABLE


def spoken_summary(card):
    """What Dan says before sending: who, by what, about what (the owner answers to this)."""
    who = card.get('to_name') or card.get('to') or '相手'
    how = CARD_CHANNELS_SPOKEN.get(card.get('channel') or '', 'メッセージ')
    what = card.get('subject') or card.get('intent') or ''
    body = ' '.join(str(card.get('body') or '').split())
    gist = body[:60] + ('…' if len(body) > 60 else '')
    return f'{who}さん宛ての{how}。' + (f'件名は「{what}」。' if what else '') + f'本文は「{gist}」。これで送っていいですか。'


def mention_of(card, text):
    """Dan's words mention the recipient (the read-aloud happened): the name, the address's user part, or the summary's frame."""
    text = str(text or '')
    for key in (card.get('to_name') or '', (card.get('to') or '').split('@')[0].lstrip('@')):
        key = key.replace('様', '').replace('さん', '').strip()
        if len(key) >= 2 and key in text: return True
    return bool(re.search(r'(宛て|あて|送っていい|送ってもいい|送りますか|送っていいですか|送信していい)', text))


def approval_heard(history, mark, card, since=None):
    """Whether the owner approved sending, read from the call's transcript after `mark` (where the transcript stood when
    the draft was last put on the stage): Dan must have read the message back (a turn mentioning the recipient) and the
    owner's latest words, after that, must be an approval without a hesitation. Words already judged (before `since`,
    the last refusal) are not judged again. Returns (ok, reason)."""
    turns = words_since(history, mark)
    read = -1
    for i, t in enumerate(turns):
        if t['role'] == 'assistant' and mention_of(card, t['text']): read = i
    if read < 0: return False, '宛先と要点をまだ読み上げていない'
    owner = [t for t in turns[read + 1:] if t['role'] == 'user' and t['text'].strip()]
    if since is not None:
        owner = [t for t in words_since(history, since) if t['role'] == 'user' and t['text'].strip()] if owner else []
    if not owner: return False, '読み上げの後の本人の返事がまだ聞こえていない'
    last = owner[-1]['text'].strip()
    if HESITATION.search(last): return False, f'本人の返事「{last[:40]}」は承認の言葉ではない'
    if not APPROVAL.search(last): return False, f'本人の返事「{last[:40]}」に承認の言葉が無い'
    return True, last[:80]


def transcript_mark(history):
    """Where the transcript stands now: (turns, characters of the last turn)."""
    return (len(history), len(history[-1]['text']) if history else 0)


def words_since(history, mark):
    """The turns after a mark (the first one cut at the mark's character)."""
    n, chars = mark or (0, 0)
    if n <= 0: return [dict(t) for t in history]
    out = []
    if n - 1 < len(history):
        head = history[n - 1]
        rest = head['text'][chars:]
        if rest.strip(): out.append({'role': head['role'], 'text': rest})
    out.extend(dict(t) for t in history[n:])
    return out


INSTRUCTIONS = """あなたは、本人がダン（音声アシスタント）と通話している間、本人の画面に出す「図」を決めて描く係です。声は出せません。画面だけです。
入力は、直前の会話（ユーザー＝本人、Dan＝ダン）、今の画面の札と中身、そして本人からの明示の頼み（あれば）です。
出力は JSON だけ: {"action": "keep" | "caption" | "replace" | "back", "caption": "今の話を6〜14文字で", "program": "部品のプログラム", "html": "自由な絵（SVG/HTML）", "image": "画像の URL", "version": 前に出した図の番号}
replace の時は program・html・image のどれか1つだけを入れる（内容に一番合う見せ方を選ぶ。下の「見せ方の選び方」）。back の時は version に「これまで出した図」の番号。

action の決め方。判断の材料は「新しく届いた言葉」（前回の判断の後に届いた分）で、直前の会話は文脈として読む:
- keep: 挨拶・相づち・短い返事・今の画面がまだ話に合っている時。新しく届いた言葉が、今の画面の内容の言い直し・補足・締めの言葉の時も keep。
- caption: 話題が少し動いたが、新しく描く構造（流れ・比較・数字・手順）が無い時。札だけ替える。
- replace: 新しく届いた言葉に、今の画面に無い「見た方が早い構造」（人・物・流れ、比べる物、金額や件数、手順、時間の推移）が出た時。本人が「図にして」「画面に出して」と頼んだ時は必ず replace（本人の頼みの対象を描く。直前にダンが説明した物）。
- back: 新しく届いた言葉が、「これまで出した図」のどれかと同じ話題に戻った時。描き直さず、その図の version を返す。
- 同じ内容を少し言い換えただけでは replace しない（画面がちらつく）。ただし、今の図に無い段階・項目・数字が足された時は、今の図と同じ型のまま全部入れて replace する（Flow なら Flow のまま箱を足す）。
- 今の画面の話題（札）の話が続いている間に、会話の前の方にあった別の話題の図をもう一度描かない（流れの図と料金の数字を行ったり来たりさせない）。
- 今の画面が本物のページの写真（（画像）で始まる）の時は、本人がそのページの話をしている間は keep。写真の中身を絵に描き直さない。
- 今の画面が送信案（（送信案）で始まる。宛先・件名・本文）の時は、本人がその文面を直したり送るかを決めたりしている間なので keep（札も据え置き）。文面の内容を図に描き直さない。
- 本人が「○○にメッセージ送って」「メールして」「返事して」と頼んだ時と、ダンがその文面を作っている間は keep。文面はダンが下書き（送信案）として画面に出すので、文面や宛先を図にしない。
- 入力はダンの話の途中（節の切れ目）でも届く。話の方向がもう分かるなら、文の終わりを待たずに描く（本人は図が声より遅れるのを嫌う）。ダンが手順や流れを1つ目から言い始めたら（「まず〜して、」）、その時点で最初の1〜2段階だけの Flow か Steps を描き、後の段階は同じ型のまま足していく。まだ何の話か分からない時だけ keep。
- 新しく届いた言葉が本人の質問で、ダンがまだ答えていない時: 手順・流れ・段取り・比べる物を聞かれたなら、質問の言葉から見出しだけの骨組み（Steps か、箱2〜3個の Flow）を描いてよい（中身はダンの言葉で育てる）。数字・料金・時間を聞かれた時は、ダンがまだ言っていないので caption で札を質問の話題に替えるだけにして、前の図を描き直さない。

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


def family(kind, body):
    """What kind of scene this is, for telling a flip (a flow -> big numbers) from growth (a flow with more boxes): the
    kind and, for a parts program, the set of parts it uses."""
    if kind != 'program': return (kind,)
    return ('program',) + tuple(sorted(set(_WORD.findall(body or '')) - {'Column', 'Row', 'Card', 'Heading', 'Text', 'Divider', 'Badge'}))


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


def decision_input(turns, caption, program, request=None, html=None, image=None, fresh=None, scenes=None, card=None):
    talk = chr(10).join(('ユーザー' if t['role'] == 'user' else 'Dan') + ': ' + t['text'].strip()[:700] for t in turns if t['text'].strip())
    shown = program or (('（自由な絵）' + chr(10) + html[:1500]) if html else '') or (('（画像）' + image) if image else '') or (card_text(card) if card else '') or '（まだ無い）'
    text = '直前の会話（新しい物が下）:' + chr(10) + talk
    if fresh:
        text += chr(10) + chr(10) + '新しく届いた言葉（前回の判断の後）:' + chr(10) + chr(10).join(('ユーザー' if r == 'user' else 'Dan') + ': ' + w.strip()[:700] for r, w in fresh if w.strip())
    text += chr(10) + chr(10) + '今の画面の札: ' + (caption or '（まだ無い）') + chr(10) + '今の画面の中身: ' + shown
    if scenes:
        text += chr(10) + 'これまで出した図（version: 札）: ' + ', '.join(f"{sc['version']}: {sc['caption'] or '（札なし）'}" for sc in scenes[-8:])
    if request: text += chr(10) + chr(10) + '本人からの明示の頼み（必ず replace で描く）: ' + request
    return text


def card_text(card):
    return '（送信案）宛先: ' + (card.get('to_name') or card.get('to') or '') + (' 件名: ' + card['subject'] if card.get('subject') else '') + ' 本文: ' + ' '.join(str(card.get('body') or '').split())[:300]


class Stage:
    """One call's stage: the listener, the file the screen reads, and the scenes shown (for the record after the call).

    A scene is one of three things: a parts program (the chat's parts), a free drawing (SVG/HTML the model wrote,
    cleaned here, drawn by the screen in a sandboxed frame) or an image (one of Dan's files or an https URL, including a
    photograph of a page taken for the owner: show_page)."""

    def __init__(self, room_id, session_id, dialogue, record, ask=None, user_id=None, speak=None):
        self.room_id, self.session_id, self.dialogue, self.record, self.user_id = room_id, session_id, dialogue, record, user_id
        self.ask = ask or ask_model
        self.speak = speak               # the call's spoken commentary (voice_sideband): what the server itself says
        self._flow_timer, self._flow_mark = None, None
        # The version counts on from the room's previous call: the screen long-polls for a version above the last one
        # it saw, so a new call restarting at 1 never reached it (2026-10-25 3rd test call: 5 scenes drawn, none shown).
        self.version = int((read_state(room_id) or {}).get('version') or 0)
        self.caption, self.program, self.html, self.image, self.page_url, self.at = '', '', '', '', '', None
        self.card = None             # a message draft on the stage (card_of), with the transcript's mark when it was last put there
        self._card_mark, self._card_refused = None, None
        self.scenes = []
        self.pending_chars, self.user_pending = 0, False
        self._fresh = []             # (role, words) since the last decision: what the model judges on
        self._owner_asked = False    # the owner spoke since the last scene: a new scene is a real change of topic, not a flip
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
                'program': self.program, 'html': self.html, 'image': self.image, 'page_url': self.page_url, 'card': self.card, 'at': self.at,
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
        if self._fresh and self._fresh[-1][0] == role: self._fresh[-1] = (role, self._fresh[-1][1] + delta)
        else: self._fresh.append((role, delta))
        if role == 'assistant':
            self.pending_chars += len(delta.strip())
            if self.user_pending and self._timer is not None: return
            if re.search(r'[。！？!?]\s*$', delta) and self.pending_chars >= MIN_CHARS * 2: wait = SENTENCE_S
            elif '、' in delta and self.pending_chars >= CLAUSE_CHARS: wait = CLAUSE_S
            else: wait = QUIET_S
        else:
            self.user_pending = True
            self._owner_asked = True
            wait = USER_S
            if self.card and self.card.get('status') == 'pending': self._schedule_flow()
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
        fresh, self._fresh = self._fresh, []
        owner_spoke = self._owner_asked   # the owner spoke since the last scene: a new scene is a real change of topic
        self._decisions += 1
        mine = self._decisions
        turns = self.dialogue.recent()[-8:] if self.dialogue is not None else []
        if not turns and not request: return None
        started = time.monotonic()
        try:
            data, usage = await asyncio.wait_for(self.ask(instructions(), decision_input(turns, self.caption, self.program, request, self.html, self.image, fresh, self.scenes, self.card)), MODEL_TIMEOUT_S)
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
        if self.card and self.card.get('status') == 'pending' and not request and action in ('replace', 'back'):
            # the owner is revising or approving a message: the listener's drawings wait (the card is the scene)
            self.record('stage_keep', elapsed_ms=elapsed, held_for='card', **usage)
            return 'keep'
        if action == 'back':
            scene = next((sc for sc in self.scenes if str(sc.get('version')) == str(data.get('version'))), None)
            if scene is None or self._same_scene(scene):
                self.record('stage_keep', elapsed_ms=elapsed, back=str(data.get('version'))[:12], **usage)
                return 'keep'
            since = time.monotonic() - self._last_replace
            if not request and not owner_spoke and since < FLIP_HOLD_S:   # going back right after a new scene is the same flip
                self.record('stage_flip_held', elapsed_ms=elapsed, kind='back', since_s=round(since, 1), **usage)
                if caption and caption != self.caption: self._apply(caption)
                return 'held'
            self._apply(caption or scene.get('caption') or self.caption, program=scene.get('program') or None, html=scene.get('html') or None,
                        image=scene.get('image') or None, page_url=scene.get('page_url') or '')
            self._last_replace = time.monotonic()
            self.record('stage_back', elapsed_ms=elapsed, version=self.version, back=scene['version'], **usage)
            return 'replace'
        if action == 'replace':
            if not drawable:
                self.record('stage_rejected', elapsed_ms=elapsed, chars=len(str(program or html or image or '')), detail=str(program or html or image or '')[:400], **usage)
                if caption and caption != self.caption: self._apply(caption)
                return 'rejected'
            kind = next(iter(drawable))
            since = time.monotonic() - self._last_replace
            if not request and not owner_spoke and since < FLIP_HOLD_S and self.scenes and family(kind, drawable[kind]) != family(*self._current()):
                # a flip to another kind of scene right after the last one: the caption follows, the scene stays
                self.record('stage_flip_held', elapsed_ms=elapsed, kind=kind, since_s=round(since, 1), **usage)
                if caption and caption != self.caption: self._apply(caption)
                return 'held'
            self._apply(caption or self.caption, **drawable)
            self._last_replace = time.monotonic()
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

    def _current(self):
        """The kind and body of the scene on the stage now."""
        if self.program: return 'program', self.program
        if self.html: return 'html', self.html
        if self.card: return 'card', self.card.get('proposal_id') or ''
        return 'image', self.image

    def _same_scene(self, scene):
        return (scene.get('program') or '', scene.get('html') or '', scene.get('image') or '', (scene.get('card') or {}).get('proposal_id') or '') == (self.program, self.html, self.image, (self.card or {}).get('proposal_id') or '')

    def _apply(self, caption, program=None, html=None, image=None, page_url='', card=None):
        """A new version for the screen: a caption alone, or a new scene (exactly one of program / html / image / card).
        A card with the same proposal as the one on the stage is a revision of that scene (one record, newest text)."""
        self.version += 1
        self.caption = caption
        self.at = datetime.now(timezone.utc).isoformat()
        if program is not None or html is not None or image is not None or card is not None:
            self._owner_asked = False
            self.program, self.html, self.image, self.page_url, self.card = program or '', html or '', image or '', page_url or '', card or None
            same = card and self.scenes and (self.scenes[-1].get('card') or {}).get('proposal_id') == card.get('proposal_id')
            if same: self.scenes[-1].update({'version': self.version, 'at': self.at, 'caption': caption, 'card': dict(card)})
            else:
                self.scenes.append({'version': self.version, 'at': self.at, 'caption': caption, 'program': self.program,
                                    'html': self.html, 'image': self.image, 'page_url': self.page_url, 'card': dict(card) if card else None})
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

    # -- the owner's words about the draft on the stage, heard by the server itself ----------------------------------
    # The speech model answered 「もっと短くして」 and 「送って」 by itself and handed nothing to the backend (2026-10-27,
    # test calls 2 and 3: the draft stayed as it was and 「送りました」 was said with nothing sent). While a draft is on the
    # stage, the server reads the owner's words, lets a small model say what they ask for, and acts: revises the
    # draft, reads it back, sends only through approval_heard. A backend tool doing the same thing meanwhile is
    # harmless: a send is guarded by the card's status, a revision is the newest text either way.
    def _schedule_flow(self):
        if self._flow_timer is not None: self._flow_timer.cancel()
        self._flow_timer = asyncio.get_running_loop().create_task(self._flow_after(FLOW_S))

    async def _flow_after(self, wait):
        await asyncio.sleep(wait)
        self._flow_timer = None
        task = asyncio.ensure_future(self.flow())
        self._tasks.add(task); task.add_done_callback(self._tasks.discard)

    async def flow(self):
        card = self.card
        if not card or card.get('status') != 'pending' or self.dialogue is None: return None
        history = self.dialogue.history
        since = words_since(history, self._flow_mark or self._card_mark)
        owner_words = ' '.join(t['text'] for t in since if t['role'] == 'user').strip()
        if not owner_words: return None
        self._flow_mark = transcript_mark(history)
        dan_words = ' '.join(t['text'] for t in since if t['role'] == 'assistant')
        started = time.monotonic()
        try:
            data, usage = await asyncio.wait_for(self.ask(FLOW_INSTRUCTIONS, flow_input(card, dan_words, owner_words)), MODEL_TIMEOUT_S)
        except Exception as exc:
            self.record('stage_flow_failed', error_type=type(exc).__name__, detail=str(exc)[:160])
            return None
        intent = str(data.get('intent') or 'other')
        elapsed = round((time.monotonic() - started) * 1000)
        if self.card is not card or card.get('status') != 'pending': return None   # changed meanwhile (the backend acted)
        if intent == 'revise':
            body = str(data.get('body') or '').strip()
            subject, to_name = data.get('subject'), data.get('to_name')
            if not body and not subject and not to_name:
                self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='empty', **usage); return None
            out = await self.revise_message(card['proposal_id'], body=body or None, subject=str(subject).strip() if subject else None, to_name=str(to_name).strip() if to_name else None)
            self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='revised' if out.get('revised') else 'failed', **usage)
            return out
        if intent in ('send', 'approve'):
            ok, why = approval_heard(history, self._card_mark, card, self._card_refused)
            if ok:
                self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='send', **usage)
                return await self.send_message(card['proposal_id'], speak=self.speak or _silent)
            # not approved yet: the message is read back (unless Dan already did, since the owner's words), then the
            # owner's next words decide
            if any(t['role'] == 'assistant' and mention_of(card, t['text']) for t in words_since(history, self._flow_mark)) or mention_of(card, dan_words):
                self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='read_back_by_dan', detail=why[:80], **usage)
                return 'read_back'
            text = spoken_summary(card)
            self.dialogue.add('assistant', text)   # the read-back counts even when the commentary is not transcribed
            if self.speak is not None:
                try: await self.speak(text)
                except Exception as exc: self.record('stage_flow_failed', error_type=type(exc).__name__, detail=str(exc)[:160])
            self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='read_back', detail=why[:80], **usage)
            return 'read_back'
        if intent == 'stop':
            self._card_refused = transcript_mark(history)   # the next answer is judged alone
            self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='held', **usage)
            return 'held'
        if intent == 'discard':
            out = await self.discard_message(card['proposal_id'])
            self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='discarded' if out.get('discarded') else 'failed', **usage)
            return out
        self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='none', **usage)
        return None

    # -- a message on the stage: drafted, revised and sent by voice ------------------------------------------------
    def _put_card(self, row, caption=None):
        card = card_of(row)
        self._apply((caption or card.get('intent') or card.get('subject') or ('メッセージ: ' + (card.get('to_name') or card.get('to') or '')))[:40], card=card)
        self._card_mark = transcript_mark(self.dialogue.history if self.dialogue is not None else [])
        self._card_refused, self._flow_mark = None, None
        self._last_replace = time.monotonic()
        return card

    async def draft_message(self, channel, to, body, subject='', to_name='', intent='', from_account=''):
        """A message draft, as the chat's card (the same record: dan_proposals, the card in the room) and on the stage."""
        started = time.monotonic()
        if not self.user_id: return {'shown': False, 'reason': 'この通話の持ち主が分からないので下書きを作れない。'}
        if not (str(channel or '').strip() and str(to or '').strip() and str(body or '').strip()):
            return {'shown': False, 'reason': '手段（email など）・宛先・本文の3つが要る。'}
        try:
            svc = _message_service()
            row = await asyncio.to_thread(svc.create_draft, user_id=self.user_id, room_id=self.room_id, channel=str(channel), to=str(to).strip(),
                                          body=str(body).strip(), subject=str(subject or '').strip() or None, intent=str(intent or '').strip() or None,
                                          to_name=str(to_name or '').strip() or None, from_account=str(from_account or '').strip() or None, show_card=True)
        except Exception as exc:
            self.record('stage_draft_failed', error_type=type(exc).__name__, detail=str(exc)[:160], elapsed_ms=round((time.monotonic() - started) * 1000))
            return {'shown': False, 'reason': f'下書きを作れなかった: {str(exc)[:120]}'}
        card = self._put_card(row)
        self.record('stage_draft', elapsed_ms=round((time.monotonic() - started) * 1000), version=self.version, channel=card['channel'])
        return {'shown': True, 'proposal_id': card['proposal_id'], 'channel': card['channel'], 'to': card['to'], 'to_name': card['to_name'],
                'subject': card['subject'], 'body': card['body'], 'sendable_now': card['sendable'],
                'note': '本人の通話画面と部屋に下書きが出た。本文は読み上げず、誰宛てに何の件かを一言。直しの頼みは revise_message_on_stage、「送って」は send_message_on_stage（読み上げて承認の言葉を聞いてから）。'}

    async def revise_message(self, proposal_id='', body=None, subject=None, to=None, to_name=None):
        """The draft revised by voice (「もっと短く」): the newest text replaces the card's, in place on the stage."""
        started = time.monotonic()
        pid = str(proposal_id or (self.card or {}).get('proposal_id') or '').strip()
        if not pid: return {'revised': False, 'reason': '直す下書きが画面に無い。先に draft_message_on_stage。'}
        try:
            svc = _message_service()
            row = await asyncio.to_thread(svc.revise_draft, pid, self.user_id, body=body, subject=subject, to=to, to_name=to_name)
        except Exception as exc:
            self.record('stage_revise_failed', error_type=type(exc).__name__, detail=str(exc)[:160], elapsed_ms=round((time.monotonic() - started) * 1000))
            return {'revised': False, 'reason': f'直せなかった: {str(exc)[:120]}'}
        card = self._put_card(row, caption=self.caption if self.card and self.card.get('proposal_id') == pid else None)
        self.record('stage_revise', elapsed_ms=round((time.monotonic() - started) * 1000), version=self.version, revision=card['revision'])
        return {'revised': True, 'proposal_id': pid, 'body': card['body'], 'subject': card['subject'], 'to': card['to'],
                'note': '画面の文面が新しい版になった。「直しました」とだけ。'}

    async def send_message(self, proposal_id='', speak=None):
        """Send the draft on the stage, only when the transcript shows Dan read it back and the owner's latest words
        approve (approval_heard). The model's own belief that it heard 「いいよ」 is not enough (2026-10-27).
        With `speak` (the call's spoken commentary) the delivery runs in the background and its result is spoken when
        it arrives: an SMTP send took 7 s in the first test call, during which the call answered nothing."""
        started = time.monotonic()
        pid = str(proposal_id or (self.card or {}).get('proposal_id') or '').strip()
        card = self.card if self.card and self.card.get('proposal_id') == pid else None
        if not card: return {'sent': False, 'reason': 'その下書きは画面に無い。先に draft_message_on_stage で出す。'}
        if card.get('status') == 'sending': return {'sent': 'sending', 'reason': '今送っている。結果は声で届く。'}
        if card.get('status') != 'pending': return {'sent': False, 'reason': 'この下書きはもう送ったか取り下げた。'}
        if not card.get('sendable'):
            self.record('stage_send_refused', reason='manual_channel', channel=card.get('channel'))
            return {'sent': False, 'reason': f'{CARD_CHANNELS_SPOKEN.get(card.get("channel"), card.get("channel"))} は通話中には送れない（ダンがブラウザで送る手段）。下書きは部屋に残っているので、通話の後にチャットから送る。'}
        history = self.dialogue.history if self.dialogue is not None else []
        ok, why = approval_heard(history, self._card_mark, card, self._card_refused)
        if not ok:
            self._card_refused = transcript_mark(history)   # these words were judged; the next answer is judged alone
            self.record('stage_send_refused', reason=why[:80])
            return {'sent': False, 'reason': why, 'read_back': spoken_summary(card),
                    'note': '送っていない。まず read_back の内容を声で言って本人の返事を待つ。本人が「いいよ」「送って」のように答えたら、もう一度 send_message_on_stage。'}
        self.card = dict(card, status='sending')   # no second send while this one is on its way
        if speak is not None:
            task = asyncio.ensure_future(self._deliver(pid, why, started, speak))
            self._tasks.add(task); task.add_done_callback(self._tasks.discard)
            return {'sent': 'sending', 'proposal_id': pid, 'to': card['to'], 'to_name': card['to_name'],
                    'note': '承認を確かめて送信を始めた。「送ります」とだけ言う。送れたかどうかは数秒後に声で本人に届くので、自分では言わない。'}
        return await self._deliver(pid, why, started, None)

    async def _deliver(self, pid, why, started, speak):
        try:
            svc = _message_service()
            row = await svc.send(pid, self.user_id, sent_by='dan')
        except Exception as exc:
            self.record('stage_send_failed', error_type=type(exc).__name__, detail=str(exc)[:160], elapsed_ms=round((time.monotonic() - started) * 1000))
            if self.card and self.card.get('proposal_id') == pid: self.card['status'] = 'pending'
            if speak is not None: await speak('送れませんでした。下書きは部屋に残っています。')
            return {'sent': False, 'reason': f'送れなかった: {str(exc)[:120]}'}
        if str(row.get('status')) != 'sent':   # a channel Dan sends by hand got locked: not sent here
            try: await asyncio.to_thread(svc.release, pid, self.user_id)
            except Exception: pass
            if self.card and self.card.get('proposal_id') == pid: self.card['status'] = 'pending'
            self.record('stage_send_refused', reason='not_sent', status=str(row.get('status')))
            if speak is not None: await speak('この手段は通話中には送れませんでした。下書きは部屋に残っています。')
            return {'sent': False, 'reason': 'この手段は通話中には送れない。下書きは部屋に残っている。'}
        card = self._put_card(row, caption=self.caption)
        self.record('stage_sent', elapsed_ms=round((time.monotonic() - started) * 1000), version=self.version, channel=card['channel'], approved_by=why[:40])
        if speak is not None: await speak('送りました。')
        return {'sent': True, 'proposal_id': pid, 'to': card['to'], 'to_name': card['to_name'], 'note': '送った。「送りました」とだけ。'}

    async def discard_message(self, proposal_id=''):
        """The owner gave the message up (「やめて」「送らないで」): the draft is withdrawn and the card leaves the stage."""
        pid = str(proposal_id or (self.card or {}).get('proposal_id') or '').strip()
        card = self.card if self.card and self.card.get('proposal_id') == pid else None
        if not card: return {'discarded': False, 'reason': 'その下書きは画面に無い。'}
        try:
            svc = _message_service()
            row = await asyncio.to_thread(svc.discard, pid, self.user_id, by='dan')
        except Exception as exc:
            return {'discarded': False, 'reason': f'取り下げられなかった: {str(exc)[:120]}'}
        self._put_card(row, caption=self.caption)
        self.record('stage_discarded', version=self.version)
        return {'discarded': True, 'note': '取り下げた。「取り下げました」とだけ。'}

    # -- the end ----------------------------------------------------------------------------------------------
    def close(self):
        if self._timer is not None: self._timer.cancel(); self._timer = None
        if self._flow_timer is not None: self._flow_timer.cancel(); self._flow_timer = None
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
            elif scene.get('card'):
                card = scene['card']
                state = {'sent': '送信済み', 'rejected': '取り下げ', 'pending': '下書き'}.get(card.get('status'), card.get('status') or '')
                lines.append(f'✉ {CARD_CHANNELS_SPOKEN.get(card.get("channel"), "メッセージ")} 宛先: {card.get("to_name") or card.get("to")}（{state}）')
                if card.get('subject'): lines.append('件名: ' + card['subject'])
                lines.append('本文: ' + ' '.join(str(card.get('body') or '').split())[:300])
        return chr(10).join(lines)


# -- pages for the stage -------------------------------------------------------------------------------------------

def screens_base():
    """Where the owner's screens are served from (the artifacts' pages): DAN_PUBLIC_BASE_URL when set, else the production
    build on this machine (3000; the public site is a tunnel to it, and the photograph is taken here)."""
    return (os.environ.get('DAN_PUBLIC_BASE_URL') or 'http://127.0.0.1:3000').rstrip('/')


async def artifact_rows(user_id):
    """The owner's registered artifacts (label, slug, preview_url), straight from the registry: the service's list()
    keeps only slugs with a page folder in this checkout, which the artifacts moved to their own backends no longer have."""
    from app.services.chat_artifact_service import ChatArtifactService
    service = ChatArtifactService()
    def read():
        return service.supabase.table(service.table).select('label,slug,preview_url').eq('created_by', user_id).order('created_at', desc=True).limit(300).execute().data or []
    return await asyncio.to_thread(read)


async def resolve_page(user_id, url='', artifact=''):
    """The URL to photograph and a short title: an https URL as given, a path on this site under the screens' base, or
    the owner's artifact whose title or slug matches the words (the longest common match wins)."""
    url = str(url or '').strip()
    if url.startswith(('http://', 'https://')): return url, ''
    if url.startswith('/'): return screens_base() + url, ''
    words = str(artifact or url or '').strip()
    if not words or not user_id: return None, ''
    try:
        rows = await artifact_rows(user_id)
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
            if token:   # the screens check the cookie (middleware) and the page reads localStorage
                parsed = urlparse(url)
                await context.add_cookies([{'name': 'done_access_token', 'value': token, 'domain': parsed.hostname, 'path': '/'}])
                await context.add_init_script(f"localStorage.setItem('done-token', {json.dumps(token)});")
            page = await context.new_page()
            await page.goto(url, wait_until='load', timeout=PAGE_TIMEOUT_S * 1000)
            await page.wait_for_timeout(900)
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(UPLOAD_DIR / name))
        finally:
            await browser.close()
    return '/api/v1/files/' + name
