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
Since 2026-10-27 the stage also carries real things the owner works on by voice: a message draft (the chat's outbound
card), a document of one of the owner's sites (an article of the X room, a script of the script room: voice_stage_docs)
and a generated picture (voice_stage_media). The server itself listens to the owner's words while one of them is on
the stage (flow) and revises, reads back and publishes only on the owner's spoken approval (approval_heard).
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
    from app.services.voice_screen_media import URL
    if URL.fullmatch(url): return url
    if re.fullmatch(r'/api/v1/files/[A-Za-z0-9._-]{1,200}', url): return url
    if re.fullmatch(r'https://[A-Za-z0-9.-]+(:[0-9]+)?/[^\s"\'<>\\]{0,1800}', url): return url
    return None


# -- a message draft on the stage (2026-10-27: 「○○さんにメッセージ送って」 → the draft is shown, revised by voice, sent by voice) --
# What the owner says that means "send it" / "not yet". The server reads the call's transcript itself: the model that
# calls send is not trusted to have heard an approval (the owner: 「送って」「いいよ」以外の言葉では送らない).
APPROVAL = re.compile(r'(いいよ|いいです|いいっす|良いよ|よいよ|送って|送信して|送っちゃって|送ろう|送る|オッケー|オーケー|おっけ|ok|okay|お願い|大丈夫|それで|はい|うん|ええ|どうぞ|ゴー|go|頼む|よろしく|やって|進めて|問題ない|承認|了解)', re.I)
HESITATION = re.compile(r'(待って|まって|まだ|やめ|止め|とめ|ちょっと|うーん|う〜ん|えーと|えっと|直し|なおし|変え|かえ|違う|ちがう|なし|ダメ|だめ|送らない|やっぱ|考え|後で|あとで|どうしよう|どうかな|かな[。？?]?$|微妙|保留|一旦|いったん|見せて|読んで|もう一回|もう一度|\?|？)', re.I)
FLOW_S = 1.0           # the owner's words about the draft on the stage settle this long before the server acts on them
READ_BACK_FRESH_S = 12.0   # a read-back this recent is not said again by the backend
ASSIST_POLL_S = 2.0       # how often the stage reads how the site's editing assistant stands
ASSIST_TIMEOUT_S = 900.0  # the X room's and the script room's workers stop at 14 minutes
ASSIST_LAY_S = 20.0       # an article's suggestions are laid on by its page: waited for this long after the worker is done
DECIDE_WAIT_S = 10.0      # the page's approve button, pressed through a command, shows in the site's state within this
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


PUBLISH_QUESTION = re.compile(r'(投稿していい|投稿してもいい|投稿しますか|投稿して大丈夫|公開していい|公開してもいい|公開しますか|公開して大丈夫|出していい|これで投稿|これで公開|投稿してよろしい|公開してよろしい)')


def doc_text(doc):
    return ('（文書）' + (doc.get('label') or doc.get('kind') or '') + (' @' + doc['account'] if doc.get('account') else '') + ' 題: ' + (doc.get('title') or '（無題）')
            + ' 状態: ' + {'draft': '下書き', 'publishing': '投稿中', 'published': '投稿済み', 'failed': '失敗'}.get(doc.get('status'), '') + ' 本文: ' + ' '.join(str(doc.get('body') or '').split())[:600])


def media_text(media):
    return '（画像' + ('を作っている' if media.get('status') == 'generating' else '') + '）' + ' '.join(str(media.get('prompt') or '').split())[:200]


def spoken_doc_summary(doc):
    """What Dan says before publishing a document: where, what, the gist (the owner answers to this)."""
    where = (doc.get('publish_label') or '公開') + ('、@' + doc['account'] + ' で' if doc.get('account') else '')
    title = doc.get('title') or ''
    body = ' '.join(str(doc.get('body') or '').split())
    return f'{where}。' + (f'題は「{title}」。' if title else '') + f'書き出しは「{body[:50]}' + ('…' if len(body) > 50 else '') + '」。これで投稿していいですか。'


def mention_of_doc(doc, text):
    """Dan's read-back of a document: it names it (the title's first characters, or 記事/投稿/台本) AND asks whether to
    publish."""
    text = str(text or '')
    if not PUBLISH_QUESTION.search(text): return False
    title = str(doc.get('title') or '').strip()
    if len(title) >= 2 and title[:6] in text: return True
    return bool(re.search(r'(記事|投稿|台本|文書|原稿)', text))


DOC_FLOW_INSTRUCTIONS = """通話中、本人の画面にはダンが作った文書（記事・投稿・台本など: 題と本文）が出ています。本人の直前の言葉が、その文書に対して何を求めているかを判定します。出力は JSON だけ:
{"intent": "revise" | "publish" | "approve" | "stop" | "other", "body": "直した本文全体（revise の時だけ）", "title": "直した題（題を変える時だけ）"}
- revise: 本文や題を変える頼み（「もっと短く」「2段落目を削って」「最後にまとめを足して」「タイトルを〜に」）。body には直した後の本文全体を書く。頼まれた所だけ変え、ほかの段落・行は一字も変えない（改行もそのまま）。本人が言った内容だけを使い、事実や数字を補わない。
- publish: 投稿・公開してほしいという頼み（「投稿して」「公開して」「出して」「ポストして」）。
- approve: ダンが文書の要点を読み上げて「投稿していいですか」と聞いた後の、承認の返事（「いいよ」「OK」「はい」「お願い」「それで」）。
- stop: 待ってほしい・保留（「ちょっと待って」「まだ」「うーん」「もう一回読んで」）。
- other: 文書と関係ない話、挨拶、相づち、ダンへの質問。
迷う時は other か stop（投稿する側に倒さない）。"""

ASSIST_FLOW_INSTRUCTIONS = """通話中、本人の画面にはダンの成果物（X運用室・台本室など）の本物の画面が開いていて、ある文書（記事・投稿・台本: 題と本文）が出ています。直しはその成果物の編集アシスタントが書き、画面に直しの案として載せます。本人はそれを反映（承認）するか取り消します。本人の直前の言葉が、その文書に対して何を求めているかを判定します。出力は JSON だけ:
{"intent": "revise" | "accept" | "reject" | "publish" | "approve" | "stop" | "other", "instruction": "編集アシスタントへの頼み（revise の時だけ）"}
- revise: 本文・題・画像を変える頼み、書いてほしい頼み（「もっと短く」「2段落目を削って」「最後にまとめを足して」「タイトルを〜に」「画像を入れて」「ここをもっと具体的に」）。instruction には本人の頼みを、本人の言った内容のまま1〜3文で書く（あなたが直した本文は書かない。言っていないことを足さない。「それ」「ここ」は画面の何を指すか分かる時だけ言い換える）。
- accept: 画面に出ている直しの案を反映・承認してほしい（「反映して」「それでいい」「全部承認」「いいね、それで」「採用」）。ダンが「投稿していいですか」と聞いた直後の「いいよ」は accept ではなく approve。
- reject: 直しの案を取り消してほしい（「戻して」「元のほうがいい」「その案はいらない」「却下」）。
- publish: 投稿・公開してほしいという頼み（「投稿して」「公開して」「ポストして」）。
- approve: ダンが文書の要点を読み上げて「投稿していいですか」と聞いた後の、承認の返事（「いいよ」「OK」「はい」「お願い」「それで」）。
- stop: 待ってほしい・保留（「ちょっと待って」「まだ」「うーん」）。
- other: 文書と関係ない話、挨拶、相づち、感想だけ、ダンへの質問。
迷う時は other か stop（投稿する側・反映する側に倒さない）。"""

MEDIA_FLOW_INSTRUCTIONS = """通話中、本人の画面にはダンが作った画像（と、その画像を作った時の頼み）が出ています。本人の直前の言葉が、その画像に対して何を求めているかを判定します。出力は JSON だけ:
{"intent": "revise" | "other", "instruction": "画像をどう直すかの指示（revise の時だけ。画像生成の指示として英語でなく日本語のまま、具体的に）"}
- revise: 画像を直す・作り直す頼み（「もっと明るく」「背景を青に」「人を入れて」「もう一枚別の構図で」）。instruction には、今の画像にどんな変更を加えるかを1〜2文で書く。
- other: 画像と関係ない話、挨拶、相づち、感想だけ（「いいね」）、ダンへの質問。
迷う時は other。"""


def doc_flow_input(doc, dan_words, owner_words):
    return ('今の文書:' + chr(10) + '題: ' + (doc.get('title') or '') + chr(10) + '本文:' + chr(10) + str(doc.get('body') or '')[:6000] + chr(10) + chr(10)
            + 'ダンの直前の言葉: ' + (' '.join(str(dan_words or '').split())[:400] or '（無し）') + chr(10) + '本人の新しい言葉: ' + ' '.join(str(owner_words or '').split())[:600])


def media_flow_input(media, dan_words, owner_words):
    return ('今の画像を作った頼み: ' + str(media.get('prompt') or '')[:400] + chr(10) + 'これまでの直し: ' + ' / '.join(str(x) for x in (media.get('history') or [])[-4:]) + chr(10) + chr(10)
            + 'ダンの直前の言葉: ' + (' '.join(str(dan_words or '').split())[:400] or '（無し）') + chr(10) + '本人の新しい言葉: ' + ' '.join(str(owner_words or '').split())[:600])


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


SEND_QUESTION = re.compile(r'(送っていい|送ってもいい|送りますか|送信していい|送信してもいい|送ってよろしい|送ってもよろしい|送信しますか|これで送|送って大丈夫|送信して大丈夫)')


def mention_of(card, text):
    """Dan's words are the read-back: they name the recipient (the name, the address's user part, or 宛て) AND ask whether
    to send. 「○○さん宛てに文面を出しました」 alone is the announcement of the draft, not a read-back (2026-10-27 test call 5:
    it counted, and the owner's first 「送って」 sent the mail without the question)."""
    text = str(text or '')
    if not SEND_QUESTION.search(text): return False
    for key in (card.get('to_name') or '', (card.get('to') or '').split('@')[0].lstrip('@')):
        key = key.replace('様', '').replace('さん', '').strip()
        if len(key) >= 2 and key in text: return True
    return bool(re.search(r'(宛て|あて|宛先)', text))


def approval_heard(history, mark, card, since=None, mention=None):
    """Whether the owner approved sending, read from the call's transcript after `mark` (where the transcript stood when
    the draft was last put on the stage): Dan must have read the message back (a turn mentioning the recipient) and the
    owner's latest words, after that, must be an approval without a hesitation. Words already judged (before `since`,
    the last refusal) are not judged again. Returns (ok, reason). `mention(card, text)` is the read-back test (a
    document's is mention_of_doc)."""
    mention = mention or mention_of
    turns = words_since(history, mark)
    read = -1
    for i, t in enumerate(turns):
        if t['role'] == 'assistant' and mention(card, t['text']): read = i
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


INSTRUCTIONS = """あなたは、本人がダン（音声アシスタント）と通話している間、画面を選んで描く係です。見せ方は本物の画面・短い札・説明の図の3つ。操作中の本物の画面を図で置き換えない。番号・短い選択・単一の数字は cue={label,value,detail,choices} の札。確認番号は 483920 のような数字で大きく、漢数字や Flow にはしない。説明が要るときだけ図。声は出せません。画面だけです。
入力は、直前の会話（ユーザー＝本人、Dan＝ダン）、今の画面の札と中身、そして本人からの明示の頼み（あれば）です。
出力は JSON だけ: {"action": "keep" | "caption" | "replace" | "back", "caption": "今の話を6〜14文字で", "program": "部品のプログラム", "html": "自由な絵（SVG/HTML）", "image": "画像の URL", "cue": {"label":"何の数字・選択か", "value":"483920", "detail":"次にすること", "choices":[]}, "version": 前に出した図の番号}
replace の時は cue・program・html・image のどれか1つだけを入れる（内容に一番合う見せ方を選ぶ。下の「見せ方の選び方」）。back の時は version に「これまで出した図」の番号。

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
- 今の画面が文書（（文書）で始まる。記事・投稿・台本の題と本文）や画像（（画像）で始まる）の時は、本人がそれを直したり投稿するかを決めたりしている間なので keep（札も据え置き）。本人が「記事を書いて」「画像を作って」と頼んだ時と、ダンがそれを作っている間も keep（記事や画像はダンが本物を画面に出す）。
- 入力はダンの話の途中（節の切れ目）でも届く。話の方向がもう分かるなら、文の終わりを待たずに描く（本人は図が声より遅れるのを嫌う）。ダンが手順や流れを1つ目から言い始めたら（「まず〜して、」）、その時点で最初の1〜2段階だけの Flow か Steps を描き、後の段階は同じ型のまま足していく。まだ何の話か分からない時だけ keep。
- 新しく届いた言葉が本人の質問で、ダンがまだ答えていない時: 手順・流れ・段取り・比べる物を聞かれたなら、質問の言葉から見出しだけの骨組み（Steps か、箱2〜3個の Flow）を描いてよい（中身はダンの言葉で育てる）。数字・料金・時間を聞かれた時は、ダンがまだ言っていないので caption で札を質問の話題に替えるだけにして、前の図を描き直さない。

描く時の選び方（本物の画面はツールが開く。ここでは札か図を作る）:
- cue（短い札）: 単一の番号・金額・日時や、2〜4個の短い選択肢。label は何の値か、value は表示用の数字・文字、detail は次にすることを1つだけ、choices は選択肢の文字列配列。番号を漢数字にしない。
- program（部品）: 人・物・流れは Flow、金額・件数・時刻は Stat、比べる話は Compare、推移は Chart、順番は Steps。構造がそのまま部品に当てはまる時。
- html（自由な絵）: 部品では表しにくい物。場所の配置・部屋や機械の図解・時間の長さを帯で見せる予定表・大小や割合を面積で見せる絵・画面の見た目の下絵・一枚絵の説明図・言葉の対比のポスター風の見せ方など。SVG を書く（<svg viewBox="0 0 640 360" width="100%" …>）。背景は暗い色（#0a0a0a 系）で、文字は白か明るい色、文字の大きさは 18px 以上、要素は10個まで。script・外部の読み込み・リンク・フォームは書かない（消される）。中身は 12000 文字まで。
- image（画像）: 会話に実在する画像の URL（/api/v1/files/… か https://）を見せる時だけ。URL を作らない。

描き方の決まり（program は OpenUI Lang。`root = Part(...)` に加え、`name = Part(...)` の行を書いて root から名前で参照できる。引数は位置で渡し、文字は二重引用符、省略できる引数は後ろから省く。name: value の書き方はしない）:
- 図は、声を聞いていない人が見ても何の話か分かる物にする。Heading の text は「この図が言っていること」を1文で（例: 「予約から乗るまでは4段階」「東京まで約2時間半・14,920円」）。Heading の sub に、図の読み方か要点を1行足す。
- 文字だけの表・箇条書きにしない。人・物・流れは Flow（アイコン＋矢印の図）、今どこかは Flow の tone "now"、金額・件数・時刻は Stat で大きく1つ、比べる話は Compare、推移は Chart、順番は Steps。
- Flow の箱の label は、それが何かが分かる言葉（「公開鍵」ではなく「アプリの鍵」、「表」ではなく「会員の表」）。箱の sub に役割や状態を短く。矢印の label は「持つ」「読める」のような動き（動詞）。名詞を3つ並べただけの Flow は描かない。
- 単一の数字は cue の value、条件は detail に書く。複数の数字を比較する時だけ Stat や Compare を使う。
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


def decision_input(turns, caption, program, request=None, html=None, image=None, fresh=None, scenes=None, card=None, doc=None, media=None):
    talk = chr(10).join(('ユーザー' if t['role'] == 'user' else 'Dan') + ': ' + t['text'].strip()[:700] for t in turns if t['text'].strip())
    shown = (program or (('（自由な絵）' + chr(10) + html[:1500]) if html else '') or (('（画像）' + image) if image else '') or (card_text(card) if card else '')
             or (doc_text(doc) if doc else '') or (media_text(media) if media else '') or '（まだ無い）')
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
        self.frame = ''              # a live page of this site on the stage (a path: /preview/<slug>…), shown as the page itself
        self.cue = None
        self.command = None          # an action for that page, passed on by the screen (frame_command): {seq, action, at}
        self._command_seq = 0
        self._screen_lock = asyncio.Lock()
        self._screen_pending = None
        self._doc_pages = {}         # doc id -> the site's own screen for it (voice_stage_docs.page)
        self.card = None             # a message draft on the stage (card_of), with the transcript's mark when it was last put there
        self._card_mark, self._card_refused = None, None
        self.doc = None              # a document of one of the owner's sites on the stage (voice_stage_docs.normal + label)
        self._doc_mark, self._doc_refused = None, None
        self.media = None            # a picture made for the stage (generate_image), its prompt and state
        self._media_mark = None
        self._read_back_at = -1e9   # when the server itself last read the draft back
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
                'program': self.program, 'html': self.html, 'image': self.image, 'page_url': self.page_url, 'frame': self.frame, 'card': self.card,
                'doc': self.doc, 'media': self.media, 'cue': self.cue, 'command': self.command, 'at': self.at,
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
        if role == 'assistant' and not self._live():
            from app.services.voice_stage_cue import from_words
            self._cue_words = (getattr(self, '_cue_words', '') + delta)[-400:]
            cue = from_words(self._cue_words)
            if cue and cue != self.cue:
                self._apply(cue['label'], cue=cue)
                self._cue_words = ''
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
            if self._live(): self._schedule_flow()
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
            data, usage = await asyncio.wait_for(self.ask(instructions(), decision_input(turns, self.caption, self.program, request, self.html, self.image, fresh, self.scenes, self.card, self.doc, self.media)), MODEL_TIMEOUT_S)
        except Exception as exc:
            self.record('stage_failed', error_type=type(exc).__name__, detail=str(exc)[:160], elapsed_ms=round((time.monotonic() - started) * 1000))
            return None
        elapsed = round((time.monotonic() - started) * 1000)
        action = str(data.get('action') or 'keep')
        caption = str(data.get('caption') or '').strip()[:40]
        program = sanitize(data.get('program')) if isinstance(data.get('program'), str) else None
        html = clean_html(data.get('html')) if data.get('html') else None
        image = safe_image(data.get('image')) if data.get('image') else None
        from app.services.voice_stage_cue import clean as clean_cue
        cue = clean_cue(data.get('cue'))
        drawable = {'cue': cue} if cue else {'program': program.strip()} if well_formed(program, self._known()) else {'html': html} if html else {'image': image} if image else None
        if request and action != 'replace' and drawable: action = 'replace'
        if mine < self._applied:
            self.record('stage_stale', action=action, elapsed_ms=elapsed)
            return None
        self._applied = mine
        if self._live() and not request and action in ('replace', 'back'):
            # the owner is revising or approving a message / document / picture: the listener's drawings wait (it is the scene)
            self.record('stage_keep', elapsed_ms=elapsed, held_for=self._live(), **usage)
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
                        image=scene.get('image') or None, page_url=scene.get('page_url') or '', frame=scene.get('frame') or None, cue=scene.get('cue'))
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
        if self.cue: return 'cue', json.dumps(self.cue,ensure_ascii=False)
        if self.program: return 'program', self.program
        if self.html: return 'html', self.html
        if self.card: return 'card', self.card.get('proposal_id') or ''
        if self.doc: return 'doc', self.doc.get('id') or ''
        if self.media: return 'media', self.media.get('id') or ''
        if self.frame: return 'frame', self.frame
        return 'image', self.image

    def _live(self):
        """What the owner is working on by voice right now (the server listens to their words for it): 'card' while a
        draft is pending, 'doc' while a document is a draft, 'media' while a picture is on the stage; '' otherwise."""
        if self.card and self.card.get('status') == 'pending': return 'card'
        if self.doc and self.doc.get('status') in ('draft', 'failed'): return 'doc'
        if self.media: return 'media'
        if self.frame: return 'frame'
        if self.image and getattr(self,'_external_source',None): return 'external'
        return ''

    def _same_scene(self, scene):
        return ((scene.get('program') or '', scene.get('html') or '', scene.get('image') or '', (scene.get('card') or {}).get('proposal_id') or '',
                 (scene.get('doc') or {}).get('id') or '', (scene.get('media') or {}).get('id') or '', scene.get('frame') or '', scene.get('cue'))
                == (self.program, self.html, self.image, (self.card or {}).get('proposal_id') or '', (self.doc or {}).get('id') or '', (self.media or {}).get('id') or '', self.frame, self.cue))

    def _apply(self, caption, program=None, html=None, image=None, page_url='', card=None, doc=None, media=None, frame=None, cue=None):
        """A new version for the screen: a caption alone, or a new scene (exactly one of program / html / image / card /
        doc / media). A card, document or picture with the same id as the one on the stage is a revision of that scene
        (one record, newest text)."""
        self.version += 1
        self.caption = caption
        self.at = datetime.now(timezone.utc).isoformat()
        if program is not None or html is not None or image is not None or card is not None or doc is not None or media is not None or frame is not None or cue is not None:
            self._owner_asked = False
            if not image: self._external_source = None
            if (frame or '') != self.frame and not (doc and (self.doc or {}).get('id') == doc.get('id')): self.command = None   # a command was for the page that leaves
            self.program, self.html, self.image, self.page_url, self.frame = program or '', html or '', image or '', page_url or '', frame or ''
            self.card, self.doc, self.media = card or None, doc or None, media or None
            self.cue = cue
            last = self.scenes[-1] if self.scenes else {}
            same = ((card and (last.get('card') or {}).get('proposal_id') == card.get('proposal_id'))
                    or (doc and (last.get('doc') or {}).get('id') == doc.get('id'))
                    or (media and (last.get('media') or {}).get('id') == media.get('id'))
                    or (frame and not doc and last.get('frame') == frame and not last.get('doc')))
            if same:
                last.update({'version': self.version, 'at': self.at, 'caption': caption, 'card': dict(card) if card else None,
                             'doc': dict(doc) if doc else None, 'media': dict(media) if media else None, 'cue': cue})
            else:
                self.scenes.append({'version': self.version, 'at': self.at, 'caption': caption, 'program': self.program,
                                    'html': self.html, 'image': self.image, 'page_url': self.page_url, 'frame': self.frame, 'card': dict(card) if card else None,
                                    'doc': dict(doc) if doc else None, 'media': dict(media) if media else None, 'cue': cue})
            del self.scenes[:-MAX_SCENES]
        self.write(active=True)

    async def show(self, what):
        """The owner asked (through the call's backend) for a drawing: decided now, with the request."""
        if self._timer is not None: self._timer.cancel(); self._timer = None
        result = await self.decide(request=str(what or '')[:400])
        return {'shown': result == 'replace', 'caption': self.caption, 'reason': None if result == 'replace' else (result or 'failed')}

    # -- a real page on the stage -----------------------------------------------------------------------------
    async def show_page(self, url='', artifact='', note=''):
        """A real page on the stage: a page of this site (one of the owner's artifacts, by name or path) as the page itself,
        live and signed in as the owner, so what the owner sees and presses is the site (the owner on 2026-10-27: every
        screen on the stage must be the real one); a page elsewhere as its photograph from a browser of this server."""
        started = time.monotonic()
        target, title = await resolve_page(self.user_id, url, artifact)
        if not target:
            self.record('stage_page_failed', reason='not_found', elapsed_ms=round((time.monotonic() - started) * 1000))
            return {'shown': False, 'reason': f'「{artifact or url}」という成果物やページが見つからなかった。'}
        caption = (str(note or '').strip() or title or target)[:40]
        own = frame_path(target)
        if own:
            self._apply(caption, frame=own)
            self._last_replace = time.monotonic()
            self.record('stage_page', elapsed_ms=round((time.monotonic() - started) * 1000), version=self.version, live=True)
            return {'shown': True, 'caption': caption, 'url': own, 'note': '本人の通話画面にその画面そのものが開いた（本人が押して操作もできる）。「出しました」とだけ。'}
        # Use the same authenticated browser the call operates, never a new anonymous browser.
        from app.services import voice_tools
        host = voice_tools.host(self.user_id,self.room_id)
        opened = await host.ask('call',name='browser',arguments={'action':'open_target','url':target,'observation':'dom'})
        out = await self.show_external('browser')
        if not out.get('shown'): out['browser_result'] = opened
        return out

    async def show_external(self, source='browser', serial=''):
        from app.services import voice_tools
        if source not in ('browser','phone'): return {'shown':False,'reason':'browser か phone を指定してください。'}
        args = {'action':'screenshot'}
        if source == 'phone' and serial: args['serial'] = serial
        out = await voice_tools.host(self.user_id,self.room_id).ask('call',with_media=True,name=source,arguments=args)
        path = safe_image(out.get('stage_image'))
        if not path: return {'shown':False,'reason':out.get('text') or '画面を取得できませんでした。'}
        self._apply('スマホの画面' if source=='phone' else 'ブラウザの画面',image=path)
        self._external_source = source
        return {'shown':True,'note':'実際の操作画面を表示しました。操作のたびに更新します。静止画なので本人が直接押すことはできません。'}

    def _command(self, action, screen_command=None):
        """An action for the page on the stage (the page's own button: approve all suggestions, reload…). The screen passes
        it to the page (frame_command in voice-stage.tsx), which runs it as if pressed; the result is read back from the site."""
        self._command_seq += 1
        self.command = {'seq': self._command_seq, 'action': action, 'at': datetime.now(timezone.utc).isoformat(), 'screen_command': screen_command}
        self.version += 1
        self.write(active=True)
        self.record('stage_command', action=action, version=self.version)

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
        live = self._live()
        if live == 'doc': return await self.doc_flow()
        if live == 'media': return await self.media_flow()
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
            # the server reads back at once (about 2 s after the owner's words; the backend's own read-back came 8 s
            # later in test call 7 and collided with the owner's next words). A backend call meanwhile is told it was
            # read already (send_message), so the owner does not hear it twice (test call 6).
            text = spoken_summary(card)
            self._read_back_at = time.monotonic()
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
            if time.monotonic() - self._read_back_at < READ_BACK_FRESH_S:
                return {'sent': False, 'reason': why, 'read_back_done': True,
                        'note': '送っていない。宛先と要点はもう声で読み上げて本人の返事を待っている。返事は空にする（重ねて読み上げない）。本人が「いいよ」「送って」のように答えたら、もう一度 send_message_on_stage。'}
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

    # -- a document of one of the owner's sites on the stage: written, revised and published by voice (2026-10-27) -------
    # An article of the X operation room or a script of the script room is the site's own record (voice_stage_docs: the
    # site declares how to create, revise and publish it), so what the owner sees in the call is what the room shows
    # afterwards. Publishing goes through the site's own send path and only after the read-back and the owner's spoken
    # approval, judged on the transcript the way a message is (approval_heard with mention_of_doc).
    def _put_doc(self, doc, caption=None):
        from app.services import voice_stage_docs
        info = voice_stage_docs.kinds().get(doc.get('kind') or '', {})
        keep = {k: (self.doc or {}).get(k) for k in ('assist',) if self.doc and self.doc.get('id') == doc.get('id')}
        doc = dict(keep, **doc)
        doc = dict(doc, label=str(info.get('label') or doc.get('kind') or ''), publish_label=str(info.get('publish') or ''), publishable=bool(info.get('publishable')),
                   assistant=bool(info.get('assistant')), page=self._doc_pages.get(doc.get('id') or '', ''))
        self._apply((caption or doc.get('title') or doc['label'] or '文書')[:40], doc=doc, frame=doc['page'] or None)
        self._doc_mark = transcript_mark(self.dialogue.history if self.dialogue is not None else [])
        self._doc_refused, self._flow_mark = None, None
        self._last_replace = time.monotonic()
        return doc

    async def draft_document(self, kind, title, body='', account='', note='', request=''):
        """A document for the owner, as the site's own record, on the site's own screen. A site with an editing assistant
        gets the owner's request and writes it there (its writing rules); otherwise the call's body is the text."""
        from app.services import voice_stage_docs
        started = time.monotonic()
        kind, request = str(kind or '').strip(), ' '.join(str(request or '').split())
        if not self.user_id: return {'shown': False, 'reason': 'この通話の持ち主が分からないので文書を作れない。'}
        assisted = voice_stage_docs.can_assist(kind)
        if assisted and not request: request = ' '.join(str(body or '').split())[:2000]
        if not assisted and not str(body or '').strip(): return {'shown': False, 'reason': '本文が要る（あなたが書く）。'}
        if assisted and not request: return {'shown': False, 'reason': '本人の頼み（request: 何の記事・台本を書いてほしいか）が要る。本文はその成果物の編集アシスタントが書く。'}
        try:
            doc = await voice_stage_docs.create(self.user_id, kind, str(title or '').strip(), '' if assisted else str(body).strip(), str(account or '').strip(), str(note or '').strip())
            self._doc_pages[doc['id']] = await voice_stage_docs.page(self.user_id, kind, doc['id'])
        except Exception as exc:
            self.record('stage_doc_failed', error_type=type(exc).__name__, detail=str(exc)[:160], elapsed_ms=round((time.monotonic() - started) * 1000))
            return {'shown': False, 'reason': f'文書を作れなかった: {str(exc)[:160]}'}
        doc = self._put_doc(doc)
        self.record('stage_doc', elapsed_ms=round((time.monotonic() - started) * 1000), version=self.version, kind=doc['kind'], chars=len(doc['body']), assisted=assisted, live=bool(doc['page']))
        if assisted:
            asked = await self._ask_assistant(doc, request, writing=True)
            if not asked.get('asked'): return {'shown': True, 'doc_id': doc['id'], 'writing': False, 'reason': asked.get('reason')}
            return {'shown': True, 'doc_id': doc['id'], 'kind': doc['kind'], 'title': doc['title'], 'writing': True,
                    'note': f'本人の通話画面に{doc["label"]}の画面が開き、その編集アシスタントが本文を書き始めた（1〜3分）。書けたら直しの案として画面に載り、声でも届く。「{doc["label"]}の画面で書いています」とだけ言う。'}
        return {'shown': True, 'doc_id': doc['id'], 'kind': doc['kind'], 'title': doc['title'], 'account': doc['account'], 'publishable_now': doc['publishable'],
                'note': '本人の通話画面に文書が出た（その成果物の中にも同じ物が残る）。本文は読み上げず、何を作ったかを一言。直しの頼みは revise_document_on_stage、「投稿して」は publish_document_on_stage（読み上げて承認の言葉を聞いてから）。'}

    async def revise_document(self, instruction=None, body=None, title=None):
        """The document revised by voice. A site with an editing assistant gets the owner's words and lays its revision on
        its own screen as suggestions; otherwise the newest text replaces the record's, in place on the stage."""
        from app.services import voice_stage_docs
        started = time.monotonic()
        doc = self.doc
        if not doc: return {'revised': False, 'reason': '直す文書が画面に無い。先に draft_document_on_stage。'}
        if doc.get('status') == 'published': return {'revised': False, 'reason': 'この文書はもう投稿した。直すなら新しく作る。'}
        if voice_stage_docs.can_assist(doc['kind']):
            instruction = ' '.join(str(instruction or '').split())
            if not instruction: return {'revised': False, 'reason': f'{doc["label"]}は編集アシスタントが直す。本人の頼みを言葉のまま instruction に渡す（本文は渡さない）。'}
            asked = await self._ask_assistant(doc, instruction)
            if not asked.get('asked'): return {'revised': False, 'reason': asked.get('reason')}
            return {'revised': 'asked', 'doc_id': doc['id'], 'note': f'{doc["label"]}の編集アシスタントに頼んだ。直しの案は画面に載り、できたら声でも届く。「頼みました」とだけ言う。'}
        if not (body and str(body).strip()) and not (title and str(title).strip()): return {'revised': False, 'reason': '直した本文（全体）か題が要る。'}
        try:
            out = await voice_stage_docs.revise(self.user_id, doc['kind'], doc['id'], title=str(title).strip() if title else None, body=str(body).strip() if body else None)
        except Exception as exc:
            self.record('stage_doc_revise_failed', error_type=type(exc).__name__, detail=str(exc)[:160], elapsed_ms=round((time.monotonic() - started) * 1000))
            return {'revised': False, 'reason': f'直せなかった: {str(exc)[:160]}'}
        out = self._put_doc(out, caption=self.caption)
        self.record('stage_doc_revise', elapsed_ms=round((time.monotonic() - started) * 1000), version=self.version, revision=out['revision'])
        return {'revised': True, 'doc_id': out['id'], 'title': out['title'], 'revision': out['revision'], 'note': '画面の文書が新しい版になった。「直しました」とだけ。'}

    # -- the site's own editing assistant, asked by voice (2026-10-27) -------------------------------------------------
    # The owner: the X room rewrites with its skill, so the call must use that screen and that function. The request goes
    # to the site's assistant as the owner said it (voice_stage_docs.assist); the site's screen on the stage shows the
    # assistant working and its suggestions; the stage follows the request (assist_state) and says when it is done.
    async def _ask_assistant(self, doc, instruction, writing=False):
        from app.services import voice_stage_docs
        started = time.monotonic()
        try:
            asked = await voice_stage_docs.assist(self.user_id, doc['kind'], doc['id'], instruction)
        except Exception as exc:
            self.record('stage_assist_failed', error_type=type(exc).__name__, detail=str(exc)[:160], elapsed_ms=round((time.monotonic() - started) * 1000))
            return {'asked': False, 'reason': f'編集アシスタントに頼めなかった: {str(exc)[:160]}'}
        request_id = str(asked.get('request_id') or '')
        if self.doc and self.doc.get('id') == doc['id']:
            self.doc = dict(self.doc, assist={'state': 'queued' if asked.get('queued') else 'running', 'instruction': instruction[:200], 'request_id': request_id, 'message': '', 'pending': 0})
            self._command('open-assistant')   # the page reads the new request and shows its assistant at work
        self.record('stage_assist', elapsed_ms=round((time.monotonic() - started) * 1000), queued=bool(asked.get('queued')), writing=writing, chars=len(instruction))
        task = asyncio.ensure_future(self._follow_assistant(doc['id'], doc['kind'], request_id, writing, time.monotonic()))
        self._tasks.add(task); task.add_done_callback(self._tasks.discard)
        return {'asked': True, 'request_id': request_id}

    async def _follow_assistant(self, doc_id, kind, request_id, writing, started):
        from app.services import voice_stage_docs
        speak = self.speak or _silent
        last, done_at = None, None
        while time.monotonic() - started < ASSIST_TIMEOUT_S:
            await asyncio.sleep(ASSIST_POLL_S)
            if not self.doc or self.doc.get('id') != doc_id: return None
            try:
                st = await voice_stage_docs.assist_state(self.user_id, kind, doc_id, request_id)
            except Exception as exc:
                self.record('stage_assist_state_failed', error_type=type(exc).__name__, detail=str(exc)[:160]); continue
            if st != last:
                last = st
                self.doc = dict(self.doc, assist=dict(self.doc.get('assist') or {}, state=st['state'], message=st['message'][:300], pending=st['pending']))
                self.write(active=True)
            if st['state'] == 'error':
                self.record('stage_assist_done', result='error', elapsed_ms=round((time.monotonic() - started) * 1000))
                await speak('編集アシスタントが止まりました。画面の会話を見てください。')
                return st
            if st['state'] != 'done': continue
            # an article's suggestions are laid on by the page itself: wait for them a little (the page is on the stage)
            if st['changes'] and not st['pending'] and st.get('laid') is False:
                done_at = done_at or time.monotonic()
                if time.monotonic() - done_at < ASSIST_LAY_S: continue
            await self._refresh_doc(doc_id, kind)
            self.record('stage_assist_done', result='changes' if st['changes'] else 'answer', pending=st['pending'], elapsed_ms=round((time.monotonic() - started) * 1000))
            if st['pending']: text = ('書きました。' if writing else '直しの案が出ました。') + 'よければ「反映して」と言ってください。'
            elif st['changes']: text = '書きました。' if writing else '直しました。'
            else: text = (st['message'] or '編集アシスタントが答えました。画面を見てください。')[:120]
            if self.dialogue is not None: self.dialogue.add('assistant', text)
            await speak(text)
            return st
        self.record('stage_assist_done', result='timeout', elapsed_ms=round((time.monotonic() - started) * 1000))
        return None

    async def _refresh_doc(self, doc_id, kind, pending=None):
        """Read the document back from its site and publish it when it changed. pending: the suggestions left after a
        decision, which the site's text does not carry (the status line went on showing 「直しの案 42件」 after they were
        all taken, 2026-10-27)."""
        from app.services import voice_stage_docs
        try:
            fresh = await voice_stage_docs.read(self.user_id, kind, doc_id)
        except Exception as exc:
            self.record('stage_doc_read_failed', error_type=type(exc).__name__, detail=str(exc)[:160]); return None
        if not self.doc or self.doc.get('id') != doc_id: return None
        if pending is not None and (self.doc.get('assist') or {}).get('pending') != pending:
            fresh = dict(fresh, assist=dict(self.doc.get('assist') or {}, pending=pending))
        if all(self.doc.get(k) == v for k, v in fresh.items()): return self.doc   # nothing changed on the site
        mark, refused, flow_mark = self._doc_mark, self._doc_refused, self._flow_mark
        out = self._put_doc(dict(self.doc, **fresh), caption=self.caption)
        self._doc_mark, self._doc_refused, self._flow_mark = mark, refused, flow_mark   # the same document: the owner's words still count
        return out

    async def decide_suggestions(self, accept=True):
        """The owner approved (or refused) the suggestions on the site's screen: the page's own 「すべて」 button does it
        (a command passed to the page), and the site's state says whether it happened."""
        from app.services import voice_stage_docs
        doc = self.doc
        if not doc or not doc.get('page') or not voice_stage_docs.can_assist(doc['kind']):
            return {'decided': False, 'reason': '直しの案が載る画面が出ていない。'}
        try:
            before = await voice_stage_docs.pending(self.user_id, doc['kind'], doc['id'])
        except Exception as exc:
            return {'decided': False, 'reason': f'直しの案を確かめられなかった: {str(exc)[:120]}'}
        if not before: return {'decided': False, 'reason': '反映を待っている直しの案は無い。'}
        self._command('accept-all' if accept else 'reject-all')
        started = time.monotonic()
        while time.monotonic() - started < DECIDE_WAIT_S:
            await asyncio.sleep(1.0)
            try: left = await voice_stage_docs.pending(self.user_id, doc['kind'], doc['id'])
            except Exception: continue
            if left < before:
                await self._refresh_doc(doc['id'], doc['kind'], pending=left)
                self.record('stage_decided', accept=accept, before=before, left=left, elapsed_ms=round((time.monotonic() - started) * 1000))
                return {'decided': True, 'left': left, 'note': '「' + ('反映しました' if accept else '取り消しました') + '」とだけ言う。'}
        self.record('stage_decide_failed', accept=accept, before=before)
        return {'decided': False, 'reason': '画面で押せなかった。本人に画面の「すべて」を押してもらう。'}

    async def publish_document(self, speak=None):
        """Publish the document on the stage, only when the transcript shows Dan read it back and the owner's latest
        words approve (approval_heard). The site's own send path does the sending with its own checks."""
        from app.services import voice_stage_docs
        started = time.monotonic()
        doc = self.doc
        if not doc: return {'published': False, 'reason': '投稿する文書が画面に無い。先に draft_document_on_stage で出す。'}
        if doc.get('status') == 'publishing': return {'published': 'publishing', 'reason': '今投稿している。結果は声で届く。'}
        if doc.get('status') == 'published': return {'published': False, 'reason': 'この文書はもう投稿した。', 'url': doc.get('url')}
        if not doc.get('publishable'):
            self.record('stage_publish_refused', reason='not_publishable', kind=doc.get('kind'))
            return {'published': False, 'reason': f'{doc.get("label") or doc.get("kind")} は通話からは投稿できない（作る・直すまで）。その成果物の画面から出す。'}
        if (doc.get('assist') or {}).get('state') in ('queued', 'running'):
            return {'published': False, 'reason': '編集アシスタントがまだ直している。終わってから。'}
        try: waiting = await voice_stage_docs.pending(self.user_id, doc['kind'], doc['id'])
        except Exception: waiting = 0
        if waiting:
            self.record('stage_publish_refused', reason='pending_suggestions', pending=waiting)
            return {'published': False, 'reason': f'画面にまだ反映していない直しの案が{waiting}件ある。反映するか取り消すか本人に聞く（反映は decide_suggestions_on_stage）。'}
        await self._refresh_doc(doc['id'], doc['kind'])   # read back and publish the text the site holds now
        doc = self.doc
        history = self.dialogue.history if self.dialogue is not None else []
        ok, why = approval_heard(history, self._doc_mark, doc, self._doc_refused, mention=mention_of_doc)
        if not ok:
            self._doc_refused = transcript_mark(history)
            self.record('stage_publish_refused', reason=why[:80])
            if time.monotonic() - self._read_back_at < READ_BACK_FRESH_S:
                return {'published': False, 'reason': why, 'read_back_done': True,
                        'note': '投稿していない。要点はもう声で読み上げて本人の返事を待っている。返事は空にする（重ねて読み上げない）。本人が「いいよ」「投稿して」のように答えたら、もう一度 publish_document_on_stage。'}
            return {'published': False, 'reason': why, 'read_back': spoken_doc_summary(doc),
                    'note': '投稿していない。まず read_back の内容を声で言って本人の返事を待つ。本人が「いいよ」「投稿して」のように答えたら、もう一度 publish_document_on_stage。'}
        self.doc = dict(doc, status='publishing')
        self.write(active=True)
        if speak is not None:
            task = asyncio.ensure_future(self._publish(doc, why, started, speak))
            self._tasks.add(task); task.add_done_callback(self._tasks.discard)
            return {'published': 'publishing', 'doc_id': doc['id'], 'note': '承認を確かめて投稿を始めた。「投稿します」とだけ言う。結果は数秒後に声で本人に届くので、自分では言わない。'}
        return await self._publish(doc, why, started, None)

    async def _publish(self, doc, why, started, speak):
        from app.services import voice_stage_docs
        try:
            out = await voice_stage_docs.publish(self.user_id, doc['kind'], doc['id'])
        except Exception as exc:
            self.record('stage_publish_failed', error_type=type(exc).__name__, detail=str(exc)[:160], elapsed_ms=round((time.monotonic() - started) * 1000))
            if self.doc and self.doc.get('id') == doc['id']: self._put_doc(dict(self.doc, status='failed', error=str(exc)[:160]), caption=self.caption)
            if speak is not None: await speak('投稿できませんでした。' + str(exc)[:80])
            return {'published': False, 'reason': f'投稿できなかった: {str(exc)[:160]}'}
        if out.get('status') != 'published':
            self.record('stage_publish_failed', reason='not_published', status=out.get('status'), detail=(out.get('error') or '')[:160])
            self._put_doc(dict(out, status='failed'), caption=self.caption)
            if speak is not None: await speak('投稿できませんでした。' + (out.get('error') or '')[:80])
            return {'published': False, 'reason': '投稿できなかった: ' + (out.get('error') or '')[:160]}
        out = self._put_doc(out, caption=self.caption)
        if out.get('page'): self._command('reload')   # the site's screen shows the post as published
        self.record('stage_published', elapsed_ms=round((time.monotonic() - started) * 1000), version=self.version, kind=out['kind'], approved_by=why[:40])
        if speak is not None: await speak('投稿しました。')
        return {'published': True, 'doc_id': out['id'], 'url': out.get('url'), 'note': '投稿した。「投稿しました」とだけ。'}

    async def doc_flow(self):
        """The owner's words about the document on the stage, acted on by the server itself (as flow does for a card)."""
        from app.services import voice_stage_docs
        doc = self.doc
        if not doc or doc.get('status') not in ('draft', 'failed') or self.dialogue is None: return None
        history = self.dialogue.history
        since = words_since(history, self._flow_mark or self._doc_mark)
        owner_words = ' '.join(t['text'] for t in since if t['role'] == 'user').strip()
        if not owner_words: return None
        self._flow_mark = transcript_mark(history)
        dan_words = ' '.join(t['text'] for t in since if t['role'] == 'assistant')
        assisted = voice_stage_docs.can_assist(doc['kind'])
        started = time.monotonic()
        try:
            data, usage = await asyncio.wait_for(self.ask(ASSIST_FLOW_INSTRUCTIONS if assisted else DOC_FLOW_INSTRUCTIONS, doc_flow_input(doc, dan_words, owner_words)), MODEL_TIMEOUT_S * 3)
        except Exception as exc:
            self.record('stage_flow_failed', error_type=type(exc).__name__, detail=str(exc)[:160])
            return None
        intent = str(data.get('intent') or 'other')
        elapsed = round((time.monotonic() - started) * 1000)
        if self.doc is not doc and (self.doc or {}).get('id') != doc.get('id'): return None
        doc = self.doc
        if doc.get('status') not in ('draft', 'failed'): return None
        if intent == 'revise':
            if assisted:
                instruction = ' '.join(str(data.get('instruction') or '').split()) or owner_words
                out = await self.revise_document(instruction=instruction)
                self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='asked' if out.get('revised') else 'failed', **usage)
                return out
            body, title = str(data.get('body') or '').strip(), str(data.get('title') or '').strip()
            if not body and not title:
                self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='empty', **usage); return None
            out = await self.revise_document(body=body or None, title=title or None)
            self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='revised' if out.get('revised') else 'failed', **usage)
            return out
        if intent in ('accept', 'reject') and assisted:
            out = await self.decide_suggestions(accept=intent == 'accept')
            self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='decided' if out.get('decided') else 'failed', **usage)
            text = ('反映しました。' if intent == 'accept' else '取り消しました。') if out.get('decided') else ('反映を待っている直しの案はありません。' if '無い' in str(out.get('reason')) else '画面で押せませんでした。画面の「すべて」を押してください。')
            self.dialogue.add('assistant', text)
            if self.speak is not None:
                try: await self.speak(text)
                except Exception as exc: self.record('stage_flow_failed', error_type=type(exc).__name__, detail=str(exc)[:160])
            return out
        if intent in ('publish', 'approve'):
            if not doc.get('publishable'):
                self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='not_publishable', **usage)
                return None
            if assisted:
                try: waiting = await voice_stage_docs.pending(self.user_id, doc['kind'], doc['id'])
                except Exception: waiting = 0
                if waiting or (doc.get('assist') or {}).get('state') in ('queued', 'running'):
                    text = '編集アシスタントがまだ直しています。' if not waiting else f'まだ反映していない直しの案が{waiting}件あります。反映してから投稿しますか。'
                    self.dialogue.add('assistant', text)
                    if self.speak is not None:
                        try: await self.speak(text)
                        except Exception: pass
                    self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='pending_suggestions', **usage)
                    return 'pending'
                await self._refresh_doc(doc['id'], doc['kind'])
                doc = self.doc
            ok, why = approval_heard(history, self._doc_mark, doc, self._doc_refused, mention=mention_of_doc)
            if ok:
                self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='publish', **usage)
                return await self.publish_document(speak=self.speak or _silent)
            if any(t['role'] == 'assistant' and mention_of_doc(doc, t['text']) for t in words_since(history, self._flow_mark)) or mention_of_doc(doc, dan_words):
                self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='read_back_by_dan', detail=why[:80], **usage)
                return 'read_back'
            text = spoken_doc_summary(doc)
            self._read_back_at = time.monotonic()
            self.dialogue.add('assistant', text)
            if self.speak is not None:
                try: await self.speak(text)
                except Exception as exc: self.record('stage_flow_failed', error_type=type(exc).__name__, detail=str(exc)[:160])
            self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='read_back', detail=why[:80], **usage)
            return 'read_back'
        if intent == 'stop':
            self._doc_refused = transcript_mark(history)
            self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='held', **usage)
            return 'held'
        self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='none', **usage)
        return None

    # -- a picture made for the stage, redone on the owner's words (2026-10-27) ------------------------------------------
    # The waiting is shown too: the picture's place (or the previous picture) with 「作っています」 while the request runs;
    # the finished picture replaces it, and a revision (「もっと明るく」) edits that picture, so the owner watches it change.
    def _put_media(self, media, caption=None, mark=True):
        """The picture's state on the stage. `mark` (a new request): the owner's words from here on are about this
        picture; a result landing keeps the mark, so words said while it was made are judged once it is there."""
        self._apply((caption or media.get('prompt') or '画像')[:40], media=media)
        if mark:
            self._media_mark = transcript_mark(self.dialogue.history if self.dialogue is not None else [])
            self._flow_mark = None
        self._last_replace = time.monotonic()
        return media

    async def generate_image(self, prompt, note='', speak=None):
        """A picture from the owner's words: the waiting is on the stage at once, the picture when it arrives."""
        prompt = ' '.join(str(prompt or '').split())
        if not prompt: return {'shown': False, 'reason': '何の画像か（prompt）が要る。'}
        from app.services import voice_stage_docs
        if self._live() == 'doc' and voice_stage_docs.can_assist(self.doc['kind']):
            # a picture for the document on the stage is made by its site's assistant, in the document (its image rules)
            return await self.revise_document(instruction='画像を作って入れてください: ' + prompt)
        if self.media and self.media.get('status') == 'generating': return {'shown': False, 'reason': '今ひとつ作っている。終わってから。'}
        media = {'id': f'pic-{int(time.time() * 1000)}', 'prompt': prompt, 'status': 'generating', 'image': '', 'previous': '', 'revision': 1, 'history': [], 'seconds': 0, 'error': ''}
        self._put_media(media, caption=(note or prompt))
        self.record('stage_media_started', version=self.version)
        task = asyncio.ensure_future(self._make_picture(media, prompt, None, speak))
        self._tasks.add(task); task.add_done_callback(self._tasks.discard)
        return {'shown': True, 'media_id': media['id'], 'note': '本人の通話画面に「作っています」が出た。10〜20秒で画像に替わる（結果は声でも届くので、自分で「できました」と言わない）。直しの頼みは revise_image_on_stage。'}

    async def revise_image(self, instruction, speak=None):
        """The picture on the stage redone with the owner's instruction (an edit of that picture)."""
        instruction = ' '.join(str(instruction or '').split())
        media = self.media
        if not media: return {'shown': False, 'reason': '直す画像が画面に無い。先に generate_image_on_stage。'}
        if media.get('status') == 'generating': return {'shown': False, 'reason': '今作っている途中。終わってから。'}
        if not instruction: return {'shown': False, 'reason': 'どう直すか（instruction）が要る。'}
        reference = media.get('image') or None
        history = list(media.get('history') or []) + [instruction]
        next_media = dict(media, status='generating', previous=media.get('image') or '', revision=int(media.get('revision') or 1) + 1, history=history, error='')
        self._put_media(next_media, caption=self.caption)
        self.record('stage_media_started', version=self.version, revision=next_media['revision'])
        prompt = (instruction if reference else media['prompt'] + '。' + instruction)
        task = asyncio.ensure_future(self._make_picture(next_media, prompt, reference, speak))
        self._tasks.add(task); task.add_done_callback(self._tasks.discard)
        return {'shown': True, 'media_id': media['id'], 'revision': next_media['revision'], 'note': '画面が「直しています」になった。10〜20秒で直した画像に替わる（結果は声でも届く）。'}

    async def _make_picture(self, media, prompt, reference, speak):
        from app.services import voice_stage_media
        started = time.monotonic()
        try:
            url, seconds, cost = await voice_stage_media.make(prompt, self.room_id, reference)
        except Exception as exc:
            self.record('stage_media_failed', error_type=type(exc).__name__, detail=str(exc)[:160], elapsed_ms=round((time.monotonic() - started) * 1000))
            if self.media and self.media.get('id') == media['id']:
                self._put_media(dict(self.media, status='failed', image=self.media.get('previous') or '', error=str(exc)[:120]), caption=self.caption, mark=False)
            if speak is not None: await speak('画像を作れませんでした。')
            return None
        if not self.media or self.media.get('id') != media['id']:
            self.record('stage_media_dropped', elapsed_ms=round((time.monotonic() - started) * 1000))
            return None
        done = dict(self.media, status='done', image=url, seconds=seconds, error='')
        self._put_media(done, caption=self.caption, mark=False)
        self.record('stage_media', elapsed_ms=round((time.monotonic() - started) * 1000), version=self.version, revision=done['revision'], cost_usd=cost, edit=bool(reference))
        if speak is not None: await speak('直しました。' if reference else 'できました。')
        if self.dialogue is not None and any(t['role'] == 'user' and t['text'].strip() for t in words_since(self.dialogue.history, self._flow_mark or self._media_mark)):
            self._schedule_flow()   # what the owner said while the picture was made is about it
        return done

    async def media_flow(self):
        """The owner's words about the picture on the stage: a revision is started by the server itself."""
        media = self.media
        if not media or self.dialogue is None: return None
        history = self.dialogue.history
        since = words_since(history, self._flow_mark or self._media_mark)
        owner_words = ' '.join(t['text'] for t in since if t['role'] == 'user').strip()
        if not owner_words: return None
        if media.get('status') == 'generating': return None   # judged once the picture is there (_make_picture schedules it; the mark stays)
        self._flow_mark = transcript_mark(history)
        dan_words = ' '.join(t['text'] for t in since if t['role'] == 'assistant')
        started = time.monotonic()
        try:
            data, usage = await asyncio.wait_for(self.ask(MEDIA_FLOW_INSTRUCTIONS, media_flow_input(media, dan_words, owner_words)), MODEL_TIMEOUT_S)
        except Exception as exc:
            self.record('stage_flow_failed', error_type=type(exc).__name__, detail=str(exc)[:160])
            return None
        intent = str(data.get('intent') or 'other')
        elapsed = round((time.monotonic() - started) * 1000)
        if self.media is not media: return None
        if intent == 'revise' and str(data.get('instruction') or '').strip():
            out = await self.revise_image(str(data.get('instruction')), speak=self.speak or _silent)
            self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='revising' if out.get('shown') else 'failed', **usage)
            return out
        self.record('stage_flow', intent=intent, elapsed_ms=elapsed, result='none', **usage)
        return None

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
            if scene.get('cue'):
                cue = scene['cue']; lines.append(cue.get('value','') + ' ' + cue.get('detail','') + ' / '.join(cue.get('choices',[])))
            elif scene.get('program'):
                lines.append('```openui-lang'); lines.append(scene['program']); lines.append('```')
            elif scene.get('html'):
                lines.append('```html'); lines.append(scene['html']); lines.append('```')
            elif scene.get('image'):
                lines.append(f'[操作画面]({scene["image"]})' if scene['image'].startswith('/api/v1/voicelog/stage/') else f'[添付画像: {scene["image"]}]')
                if scene.get('page_url'): lines.append(scene['page_url'])
            elif scene.get('card'):
                card = scene['card']
                state = {'sent': '送信済み', 'rejected': '取り下げ', 'pending': '下書き'}.get(card.get('status'), card.get('status') or '')
                lines.append(f'✉ {CARD_CHANNELS_SPOKEN.get(card.get("channel"), "メッセージ")} 宛先: {card.get("to_name") or card.get("to")}（{state}）')
                if card.get('subject'): lines.append('件名: ' + card['subject'])
                lines.append('本文: ' + ' '.join(str(card.get('body') or '').split())[:300])
            elif scene.get('doc'):
                doc = scene['doc']
                state = {'published': '投稿済み', 'publishing': '投稿中', 'failed': '投稿できず', 'draft': '下書き'}.get(doc.get('status'), doc.get('status') or '')
                lines.append(f'📝 {doc.get("label") or doc.get("kind")}' + (f' @{doc["account"]}' if doc.get('account') else '') + f'（{state}）' + (f' {doc["url"]}' if doc.get('url') else ''))
                if doc.get('title'): lines.append('題: ' + doc['title'])
                lines.append('本文: ' + ' '.join(str(doc.get('body') or '').split())[:300])
            elif scene.get('media'):
                media = scene['media']
                if media.get('image'): lines.append(f'[添付画像: {media["image"]}]')
                lines.append('🎨 ' + str(media.get('prompt') or '')[:120] + (' → ' + ' / '.join(str(x) for x in media['history'][-3:]) if media.get('history') else ''))
            elif scene.get('frame'):
                lines.append('🖥 ' + scene['frame'])
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


FRAME_PREFIXES = ('/preview/',)


def frame_path(target):
    """The path to open live on the stage when the target is a screen of this site ('' otherwise). /artifacts/<slug> is
    the build's copy behind the cookie check; /preview/<slug> is the same site, current, signed in by the page itself."""
    from urllib.parse import urlparse
    parsed = urlparse(str(target or ''))
    hosts = {urlparse(screens_base()).netloc, urlparse(os.environ.get('DAN_PUBLIC_ORIGIN') or 'https://dan.paina.info').netloc}
    if parsed.netloc and parsed.netloc not in hosts: return ''
    path = parsed.path or ''
    if path.startswith('/artifacts/'): path = '/preview/' + path[len('/artifacts/'):]
    if not path.startswith(FRAME_PREFIXES) or '..' in path: return ''
    return path + (('?' + parsed.query) if parsed.query else '')


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


