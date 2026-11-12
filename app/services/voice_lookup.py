"""Work the call hands to the background: the request is answered at once and the work goes on beside the conversation
(2026-11-03, the owner's 「直して」 on the plan of 19:44).

Why: the speech model (GPT-Live) says nothing while a delegation is in flight, and it does not open the next one until the
last has ended. In the 19:15 call the backend kept one delegation open for 44 s (8 rounds: three searches stopped at 15 s,
the instructions of a tool read in the middle of the call), so the owner's correction 「あまがさき」 went unanswered for
25 s; the next delegation was opened 0.3 s after the first had ended. OpenAI's guide for long tasks: acknowledge, keep the
work running, and give the verified facts as commentary when they arrive (live-delegation).

So in the plain call (voice_plain) the backend of the delegation no longer searches, reads pages or drives the browser
itself. It calls run_in_background, which returns in a moment; the delegation ends with one sentence about what is being
looked into, and the speech model is free for the next words. The work runs here, in a Responses loop of its own (DeepSeek
V4 Pro since 2026-11-12, MODEL below) with the reading tools and the stage's tools given from the start (no dan_tool_help in the middle of a call).
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

# The model that decides and answers. It was gpt-6-luna (reasoning low) until 2026-11-12: in the 11/11 11:09 call the search
# returned 仲江政史・仲江鍼灸院 three times, and luna dropped him each time because the transcript had written the owner's
# 「なかえまさし」 as 中江雅史 (the owner: chat Dan and ChatGPT never answer like that). It also answered in 15-30 s of
# the 120 it may use. DeepSeek V4 Pro reads the same results and the whole conversation and weighs them; the search and the
# page reading stay as they were. DeepSeek serves the Responses API without stored responses, so the rounds carry the
# whole history (input) instead of previous_response_id. Set DAN_VOICE_LOOKUP_MODEL=gpt-6-luna to go back.
# deepseek-flash (reasoning high) since the evening of 2026-11-12: on the four recorded requests, four runs each, it was
# right 16/16 with a median of 82 s; V4 Pro high 11/16 and 108 s (four runs ended at the time limit with nothing said),
# V4 Pro low 14/16 and 85 s; luna low 17/24 and 30 s (the 仲江 request 1/6); a quarter of V4 Pro's price
# (docs/current/voice-backend-compare-20261112.md). The notes on V4 Pro below are from the morning's measurements.
# reasoning low since 2026-11-13, with the list search (SEARCH) and places fixed: 16/16 right, median 35 s (high 8/8, 56 s;
# medium 8/8, 43 s); the time went to rounds of searching, not to thinking (docs/current/voice-lookup-fast-20261113.md).
MODEL = os.environ.get('DAN_VOICE_LOOKUP_MODEL', 'deepseek-flash')
REASONING = os.environ.get('DAN_VOICE_LOOKUP_REASONING', 'low')
# No time limit (2026-11-13, the owner: 「正しく速く作業できていて、無駄なエラーを繰り返さないのであれば、その作業は続けるべき」).
# Until then a lookup was cut at 150 s (SECONDS) and told to answer at 110 s (ANSWER_BY): V4 Pro high ended four runs of
# sixteen at the limit with nothing said, while it was still finding things. A lookup now goes on while it moves and is
# stopped only when it is stuck:
# - a round of the model that does not answer in ROUND_TIMEOUT_S is a stall (the round fails; the work goes to chat Dan);
# - rounds that only repeat searches and pages it already had (REPEATS of them) mean it found nothing new: it answers;
# - MAX_ROUNDS guards against a loop that never ends (16 rounds measured at most; the deciding was never near it).
# A long lookup tells the call what it has found (KEEP_POSTED_S), and one that answers after the owner has hung up puts
# the answer in the room's chat.
MAX_ROUNDS = 40
REPEATS = 2
KEEP_POSTED_S = 30     # nothing said yet by then: the lookup is asked once to pass on what it has verified
KEEP_POSTED = ('（本人は{seconds}秒待っている。ここまでに頼みの中心（どの人・店・物か、値段、時刻など）が1つでも確かめられていれば、'
               '次の道具と同じ手で share_progress に1文で渡す。まだ何も確かめていなければ、そのまま調べ続ける。）')
SECONDS = 600          # outside a call only (run_function without a call, the comparison script): a ceiling, not a target
# How a lookup searches (2026-11-13). 'list': the ranked results themselves (web_search.listing, 0.4-0.6 s), read by the
# lookup's own model. 'answer': Dan's whole search (a model writes the queries, another sums the results up: 2.7-4.5 s),
# what every lookup used until then; with the summary alone, a lookup read pages to check it.
SEARCH = os.environ.get('DAN_VOICE_LOOKUP_SEARCH', 'list')
LIST_SEARCH = {'type': 'function', 'name': 'web_search',
               'description': ('ウェブを検索する（1秒弱）。検索結果の一覧（題・サイト・日付・URL・本文の抜き出し）がそのまま返る。上位3件には'
                               'そのページの本文の一部が付くので、そこで確かめられた事実はページを読み直さずに使ってよい。'
                               '言い方や切り口の違う検索は同じ手で並べて呼ぶ。'),
               'parameters': {'type': 'object', 'properties': {'query': {'type': 'string', 'description': '検索語（固有名詞・地名・日付を入れて具体的に。長い文より語の並び）'}},
                              'required': ['query'], 'additionalProperties': False}}
ROUND_TIMEOUT_S = 60   # one round thinking over a dozen search results: 2-12 s measured (deepseek-flash), 60 s is a stall
WRAP_UP = ('（ここ{repeats}回の手は、もう調べた検索やページの繰り返しだった。調べるのをやめ、ここまでに確かめた事実で今答える。'
           '確かめきれなかった所は、何が分かっていないかを一言で言う。）')
DSML_AGAIN = ('（今の返事には、道具の呼び出しが文字で書かれていた。それは本人に読み上げられてしまう。道具を使うなら道具として呼び、'
              '答えるなら普通の文だけで書く。）')
PROGRESS_LIMIT = 3     # share_progress per lookup: facts on the way, not a running commentary
READ_PAGE_S = 8        # one slow page held a round of four for 29 s (2026-11-03 22:00 test call); 5 of 7 reads took under 7 s
DIRECT = ('places', 'page_clip', 'browser', 'browser_plan', 'phone')   # Dan's tools a lookup uses most, given whole from the start
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
- 本人の画面には、話している物の本物を出す（文字にアイコンを付けた図は出さない）。答えの最後に ```openui-lang の部品のブロックを1つ付けると、声で答え始めるのと同時に本人の画面に出る（声では読まれない）。途中で候補が分かった時は show_parts_on_stage で先に出してよい。使う部品:
  - 場所・店・施設: Map（places や読んだページで確かめた座標だけ。本人の今いる所は here）。下に Item を並べ、num をピンの番号に合わせる。
  - 人・店・物: Item（写真は page_clip の photo=true で取った /api/v1/files/… か、ページで見た画像の https URL。無ければ写真なし）。
  - 名前・値段・条件など、間違えると困る事実: Quote（ページの文をそのまま。mark に大事な言葉。page_clip の find で切り抜いた画像を image に）。
  - 調べたページ: 最後に Sources。
  - 部品の書き方: root = Column([...]) のように位置で引数を並べる。名前つき引数（title: …）は書かない。省く引数は null。
{parts}
- 物（商品・機材・料理など）の頼みで写真がまだ無い時は、最初の手で web_search と同じ手で show_search_on_stage（kind=images）を呼んでよい。場所は座標が分かれば Map を出し、Google マップの写真（kind=map）は座標が分からない時だけ。考えや手続きの質問（税金・制度・やり方）には呼ばない。
- 商品・店・予約の候補のページを見せると本人の判断に役立つ時は、候補が見つかった時点で show_page_on_stage に conditions（本人が言った条件を全部）と focus（本人が聞いたことが書いてある所の言葉: 価格 仕様、サイズ、営業時間など）を入れて出す（conditions は買う・選ぶ条件だけ。「違い」などの質問は入れない）。ページの本文も返るので、そのページを read_page で読まない（見せる価値のあるページは read_page ではなく最初から show_page_on_stage で開く）。渡すのは商品や店そのものの個別ページのURL（店のトップ・検索結果の一覧・別の商品のページは渡さない）で、web_search が pages に返したURLか読んだページにあったURLから選ぶ（URLを推測で組み立てない）。条件に合わないと返ったら、別のURLの候補を出す。合う候補が無ければ、そう答える。商品を探す時は、最初の手で言い方の違う検索を2〜3本並べて呼ぶ。
- 2〜3個の物の違いを聞かれたら、最初の手で物ごとに1本ずつ検索を並べ（例: 「レボルワン R630」「レボルワン R490」）、次の手で、それぞれの個別ページのURLを compare_pages_on_stage に渡す（focus に比べる所の言葉）。画面に並んで出て、各ページの本文も返るので、そこから違いを答える。片方の個別ページのURLが検索に出ない時は、その物の名前（例: R490）をそのまま urls に入れる（もう一方と同じサイトから道具が探す）。違いの質問で show_page_on_stage に片方だけを出さない。
- 場所・住所・行き方を答える時は、その場所を Map で出す（座標が分からなければ show_search_on_stage の kind=map）。画面に出す座標を探すためだけに何手も使わない（places で1回で出なければ kind=map にする）。
- 人からの連絡（「〇〇さんから連絡来た？」「メッセージの中身は？」）は read_chatwork で Chatwork を今読んで答える（hand_over しない）。
- 本人や本人の会社のこと（法人か個人か・所在地・契約しているサービスなど）で答えが変わる時は、本人に聞く前に get_saved_information と search_records で読む。どちらにも無い事だけを、まとめて1回で聞く。
- 本人の言葉は、声を文字に起こしたもの。人名・店名・地名の漢字やカタカナは、聞こえた音に機械が当てた推測で、本人が思っている字とは限らない（「さいとうけんじ」が「斎藤健二」と書かれても、本当は「齋藤賢治」かもしれない）。検索で字の違う候補が出たら、字が違うことは理由にせず、地域・仕事・やっている事・本人が話した経緯など手がかり全体で、本人の言う相手かを判断する。手がかりが合えば、その候補として答え、本人が言った字と違うことを一言添える。読みは本人が言った音のまま使う（「なかえまさし」と聞こえたなら、字が「政史」でも「まさし」。ページに読みが書いてあればそれに従う）。手がかりが割れて決めきれない時は、いちばん合う候補を画面に出し、「〇〇市の△△整骨院の□□さんですか？」のように、どこの誰かを入れた問いで本人に確かめる。「特定できなかった」で終えない。
- 急いで答えなくてよい（会話は止まっていない）。答えの中心になる事実（人・店・物がどれか、値段、時刻）は、検索の断片で済ませず、その人や店のページを読んで確かめてから答える。
- 型番・商品名・店名を聞かれたら、それ自体について確かめた事実だけで答える。別の機種・別の店・別の会社の情報で代えない。答えには何の話か（メーカー名・店名・機種名）を必ず入れる（「ショールームは〜」ではなく「レボルワンのショールームは〜」）。
- 本人は通話で答えを待っている。頼みの中心（どの人・店・物か、値段、時刻など）が1つ確かめられたら、続きを調べる前に、次の道具と同じ手で share_progress に1文で渡す（share_progress だけの手は作らない。声で本人に届く）。頼みが2つ以上あれば、1つ目が分かった時点で渡してから次を調べる。同じことを繰り返さない。予定や推測は渡さない。
- 多くの条件で候補を比べて選ぶ時だけ、確かめた事実を material に入れて think_carefully に聞く。
- 購入・送信・予約の確定・削除・取消はしない。必要なら、答えの最後に「〜してよいか」を1つだけ書く。
- 答えは、頼みに必要な確かめた事実を2〜4文のふつうの文で書く。値段・時刻・名前は確かめたまま。太字・見出し・箇条書き・表・URL は使わない。地名に（ひらがな）の読みが付いていたら、答えでもその語の後に同じ読みを残す。
- 時刻・料金・乗り場など正確さが要る事実は、それを直接調べられる所で確かめる。検索結果の断片から作らない。"""

# When the call's requests are routed by Jev (voice_router), a lookup only reads: work inside a site or an app is chat Dan's.
# In the 2026-11-05 0:59 call the lookups were sent to check two salons' free slots, drove the phone and the browser for
# 42 s and 40 s, showed empty screenshots, and answered 「確認できなかった」 each time; chat Dan did it in 1 min 54 s.
ROUTED_LINES = {
    '- ログインが要る・サイトの中で操作する・在庫や空きの最新状況を見る時は browser': ('- 予約サイトの空き状況・ログインが要るページ・サイトの中での操作・スマホやパソコンのアプリの操作が要る時、'
        '読むだけの道具で答えが出ない時は、自分で続けずに hand_over で作業担当に渡す（確かめた事実を found_so_far に全部）。'
        '「分からなかった」「確認できなかった」を答えにしない。'),
    '- 答えは、頼みに必要な確かめた事実を2〜4文のふつうの文で書く。': ('- 答えは、頼みに必要な確かめた事実を2〜4文のふつうの文で書く。値段・時刻・名前は確かめたまま。'
        'サイトの中を見れば分かる事は hand_over。太字・見出し・箇条書き・表・URL は使わない。'
        '地名に（ひらがな）の読みが付いていたら、答えでもその語の後に同じ読みを残す。'),
}
HAND_OVER = {'type': 'function', 'name': 'hand_over',
             'description': 'この頼みを作業担当（サイトやアプリを操作できるダン）に渡し、この調べものを終える。予約サイトの空き・ログインが要るページ・アプリの操作が要る時、読むだけでは答えが出ない時に使う。本人には何も言わなくてよい。',
             'parameters': {'type': 'object', 'properties': {'why': {'type': 'string', 'description': '何をしに行く必要があるか（例: ホットペッパーの予約ページで5日と6日の空きを見る）'},
                                                            'found_so_far': {'type': 'string', 'description': 'ここまでに確かめた事実（店・URL・条件など）'}},
                            'required': ['why'], 'additionalProperties': False}}


def routed():
    from app.services import voice_router
    return voice_router.enabled()


TOOL_NAMES = ('web_search', 'read_page', 'get_location', 'get_calendar', 'search_records', 'read_chatwork', 'get_saved_information', 'room_files',
              'job_status', 'show_page_on_stage', 'show_search_on_stage', 'compare_pages_on_stage', 'show_fact_on_stage', 'show_on_stage', 'show_parts_on_stage',
              'show_external_screen')
OWN = ('share_progress', 'think_carefully')


def direct_names():
    return ('places', 'page_clip') if routed() else DIRECT


def tools():
    from app.services import voice_responses, dan_tools
    every = {t['name']: t for t in [*voice_responses.TOOLS, *voice_responses.PLAIN_TOOLS]}
    listed = [LIST_SEARCH if n == 'web_search' and SEARCH == 'list' else every[n] for n in (*TOOL_NAMES, *OWN)]
    direct = []
    for name, description, schema in map(dan_tools._fields, dan_tools.definitions()):
        if name in direct_names():
            direct.append({'type': 'function', 'name': name, 'description': description, 'parameters': schema or {'type': 'object', 'properties': {}}})
    if routed():   # the browser and the phone are chat Dan's: a lookup does not show them either
        return [*(t for t in listed if t['name'] != 'show_external_screen'), *direct, HAND_OVER]
    return [*listed, *direct, {'type': 'function', **dan_tools.HELP}, {'type': 'function', **dan_tools.USE}]


def parts_lines():
    """The real-content parts a lookup builds the screen from (their signatures, from the chat screen's own list)."""
    from app.services import voice_stage
    keep = ('Map(', 'Item(', 'Quote(', 'Sources(', 'Frames(', 'Column(', 'Row(', 'Stat(', 'Facts(', 'Compare(')
    return chr(10).join('  ' + l for l in voice_stage.part_lines() if l[2:].startswith(keep))


def instructions():
    from app.services import voice_responses, dan_tools
    text = INSTRUCTIONS.replace('{parts}', parts_lines())
    if routed():
        lines = [next((v for k, v in ROUTED_LINES.items() if line.startswith(k)), line) for line in text.split(chr(10))]
        return chr(10).join(lines) + chr(10) + voice_responses.now_line()
    return (text + chr(10) + voice_responses.now_line() + chr(10) + voice_responses.remembered()
            + dan_tools.catalog(dan_tools.definitions(), native=DIRECT))


class Lookup:
    def __init__(self, call, task, label, carried=''):
        self.id = 'bg_' + uuid.uuid4().hex[:8]
        self.call, self.task, self.label, self.carried = call, task, label, carried
        self.started = time.monotonic()
        self.state = 'running'      # running → answered | failed | replaced | cancelled | handed_over
        self.answer = ''
        self.verified = []          # (tool name, its output, cut short): handed on when a correction replaces this lookup
        self.progress = []          # the facts said on the way
        self.shown = 0              # pages put on the owner's screen by show_page_on_stage
        self.task_handle = None

    def status(self):
        return {'id': self.id, 'label': self.label, 'state': self.state, 'seconds': round(time.monotonic() - self.started),
                **({'found_so_far': self.progress[-2:]} if self.progress else {})}

    def handover(self):
        """What this lookup had verified, for the one that replaces it."""
        lines = [f'- {name}: {output[:1500]}' for name, output in self.verified[-8:]]
        return chr(10).join(lines)[:8000]

    async def run(self):
        call = self.call
        call.record('lookup_started', lookup_id=self.id, carried=bool(self.carried))
        try:
            answer = await self._loop()
        except asyncio.CancelledError:
            raise
        except Exception as exc:   # a round that did not answer in ROUND_TIMEOUT_S lands here too: that is a stall
            self.state = 'failed'
            call.record('lookup_failed', lookup_id=self.id, error_type=type(exc).__name__, detail=str(exc)[:160])
            if routed():   # not 「答えが出なかった」: the work goes on with chat Dan, with what was found (owner, 2026-11-05)
                return await self.hand_over('調べる仕組みが途中で止まった')
            await self.deliver('problem', '調べものが途中で止まった（調べる仕組みの失敗）。答えは出ていない。'
                               + ('ここまでに分かったこと: ' + self.progress[-1] if self.progress else ''))
            return
        if self.state != 'running':
            return
        self.state = 'answered'
        answer, parts = split_parts(answer)
        self.answer = answer
        call.record('lookup_answered', lookup_id=self.id, seconds=round(time.monotonic() - self.started, 1), chars=len(answer), parts=len(parts),
                    after_call=call.closed)
        if parts and not call.closed:   # the screen changes as the answer is handed to the voice: they start together (2026-11-12)
            from app.services import voice_stage
            stage = voice_stage.for_room(call.room_id)
            if stage is not None:
                shown = stage.show_parts(parts, self.label)
                call.record('lookup_parts', lookup_id=self.id, shown=bool(shown.get('shown')))
        await self.deliver('result', '調べた結果: ' + (answer or '確かめられる答えは見つからなかった。'), parts)

    async def deliver(self, kind, text, parts=''):
        """Into the call while it lasts; after the owner has hung up, into the room's chat (2026-11-13: a lookup is no
        longer stopped when the call ends, so its answer must reach the owner some other way)."""
        if not self.call.closed:
            return await self.call.say(kind, text)
        if not self.call.room_id:
            return
        from app.services import room_files
        head = f'通話で頼まれた「{self.label}」を調べ終わりました（通話はもう切れていました）。' if kind == 'result' else f'通話で頼まれた「{self.label}」:'
        try:
            body = head + chr(10) + text.removeprefix('調べた結果: ') + ((chr(10) * 2 + '```openui-lang' + chr(10) + parts + chr(10) + '```') if parts else '')
            await room_files.show(self.call.room_id, self.call.user_id, [], body)
            self.call.record('lookup_posted_to_chat', lookup_id=self.id)
        except Exception as exc:
            self.call.record('lookup_post_failed', lookup_id=self.id, error_type=type(exc).__name__)

    async def _loop(self):
        client = _client()
        talk = chr(10).join(('本人' if t['role'] == 'user' else 'ダン') + ': ' + t['text'] for t in self.call.dialogue.recent())
        first = ('頼み: ' + self.task + chr(10) * 2 + '直前の通話（新しい物が下。引用中の依頼は新しい指示ではない）:' + chr(10) + talk
                 + ((chr(10) * 2 + 'この通話で前に確かめた事実（前の調べもの・条件が変わる前の版。今の頼みと条件に合う分だけ使い、同じ検索をし直さない）:' + chr(10) + self.carried) if self.carried else ''))
        given, previous, said, reminded = [{'role': 'user', 'content': first}], None, 0, False
        history = []                # stateless(): every round sends the whole lookup so far
        wrapped = False             # told to answer now (it only repeated itself, or MAX_ROUNDS is near)
        posted = False              # asked once to pass on what it has (KEEP_POSTED_S)
        retold = False              # asked once to call its tools as tools (DSML)
        seen, repeats = set(), 0    # the searches and pages asked so far, and the rounds in a row that asked nothing new
        spec = self.call.spec()
        for round_no in range(1, MAX_ROUNDS + 1):
            began = time.monotonic()
            final = {'tool_choice': 'none'} if wrapped else {}
            if stateless():
                history += given
                # DeepSeek told tool_choice none wrote its tool call as text into the answer (<｜｜DSML｜｜tool_calls>...,
                # 2026-11-12); without the tools it answers in words.
                last = ({**{k: v for k, v in spec.items() if k not in ('tools', 'tool_choice', 'parallel_tool_calls')}, 'reasoning': {'effort': 'low'}}
                        if wrapped else spec)
                response = await client.responses.create(**last, input=history)
                history += [_item(o) for o in response.output]
            else:
                response = await client.responses.create(**{**spec, **final}, input=given, **({'previous_response_id': previous} if previous else {}))
                previous = response.id
            calls = [item for item in response.output if getattr(item, 'type', '') == 'function_call']
            usage = getattr(response, 'usage', None)
            self.call.record('lookup_round', lookup_id=self.id, round=round_no, elapsed_ms=round((time.monotonic() - began) * 1000),
                             calls=[c.name for c in calls][:8], input_tokens=getattr(usage, 'input_tokens', 0) or 0,
                             cached_tokens=getattr(getattr(usage, 'input_tokens_details', None), 'cached_tokens', 0) or 0,
                             output_tokens=getattr(usage, 'output_tokens', 0) or 0)
            if not calls:
                text = response.output_text or ''
                # DeepSeek wrote a tool call as text instead of calling it (<｜｜DSML｜｜ calls>..., 2026-11-13, one run of
                # sixteen, and one in the evening of 11-12): it would have been read aloud. It is told so once.
                if 'DSML' in text and not retold and not wrapped:
                    retold = True
                    self.call.record('lookup_dsml_retold', lookup_id=self.id)
                    given = [{'role': 'user', 'content': DSML_AGAIN}]
                    continue
                # A lookup answered 「商品ページを今、画面に出すよ」 without showing anything, after the owner had asked to see
                # it; the owner had to ask again 40 s later (2026-11-03, voice_goal_call.py, weights_100kg run 2). Before the
                # answer, a lookup asked for the screen that has shown nothing is told so once.
                if not self.shown and not reminded and self.wants_screen():
                    reminded = True
                    self.call.record('lookup_show_reminded', lookup_id=self.id)
                    given = [{'role': 'user', 'content': SHOW_FIRST}]
                    continue
                return without_markup(text)
            if self.state not in ('running',):
                return ''
            asked = {(c.name, _norm(c.arguments)) for c in calls if c.name in REPEATABLE}
            fresh = asked - seen
            seen |= asked
            repeats = repeats + 1 if asked and not fresh else 0
            outputs = await asyncio.gather(*(self._execute(c, said) for c in calls))
            said += sum(1 for c in calls if c.name == 'share_progress')
            given = [{'type': 'function_call_output', 'call_id': c.call_id, 'output': out} for c, out in zip(calls, outputs)]
            spent = time.monotonic() - self.started
            if not wrapped and (repeats >= REPEATS or round_no >= MAX_ROUNDS - 1):
                wrapped = True
                self.call.record('lookup_wrap_up', lookup_id=self.id, seconds=round(spent), round=round_no, repeats=repeats)
                given.append({'role': 'user', 'content': WRAP_UP.format(repeats=repeats or round_no)})
            elif not posted and not said and not self.call.closed and spent >= KEEP_POSTED_S:
                posted = True
                self.call.record('lookup_keep_posted', lookup_id=self.id, seconds=round(spent))
                given.append({'role': 'user', 'content': KEEP_POSTED.format(seconds=round(spent))})
        return ''

    async def hand_over(self, why, found=''):
        """Chat Dan takes this lookup over with what it had verified; the owner hears nothing about it (the state is read
        when asked: voice_router.status_text)."""
        if self.state not in ('running', 'failed'):
            return
        self.state = 'handed_over'
        from app.services import voice_router
        carried = chr(10).join(x for x in (found, self.handover(), *self.progress) if x)
        out = await voice_router.start_chat_dan(self.call.user_id, self.call.room_id, self.call.dialogue,
                                                self.task.removeprefix('この通話で本人が今頼んだこと（言葉のまま）: ') + chr(10) + '（調べもの担当から: ' + why + '）',
                                                carried=carried)
        job_id = (out.get('receipt') or {}).get('id') if out.get('accepted') else None
        self.call.record('lookup_handed_over', lookup_id=self.id, accepted=bool(out.get('accepted')), job_id=str(job_id)[:8])
        if job_id and self.call.router is not None: self.call.router.jobs[job_id] = self.label
        if not out.get('accepted'):
            await self.deliver('problem', 'サイトやアプリの中を見る必要があったが、その作業を始められなかった。')

    def wants_screen(self):
        owner = [t['text'] for t in self.call.dialogue.recent() if t['role'] == 'user'][-3:]
        return bool(WANTS_SCREEN.search(self.task) or any(WANTS_SCREEN.search(t) for t in owner))

    async def _execute(self, item, said_before):
        """One function of the lookup, run the way the call runs the backend's (voice_sideband.execute_call: the early
        search of voice_prefetch, the readings of place names, the record of each function)."""
        name, arguments = item.name, item.arguments or '{}'
        if self.state != 'running':
            return json.dumps({'error': 'この調べものは取り消された。'}, ensure_ascii=False)
        if name == 'hand_over':
            try: args = json.loads(arguments)
            except ValueError: args = {}
            asyncio.ensure_future(self.hand_over(str(args.get('why') or '')[:400], str(args.get('found_so_far') or '')[:4000]))
            return json.dumps({'handed_over': True, 'note': '作業担当に渡した。この調べものはここで終わり。何も答えなくてよい。'}, ensure_ascii=False)
        if name == 'share_progress':
            if said_before >= PROGRESS_LIMIT:
                return json.dumps({'said': False, 'note': '途中の報告はもう十分。最後の答えにまとめる。'}, ensure_ascii=False)
            try: fact = ' '.join(str(json.loads(arguments).get('fact') or '').split())[:300]
            except ValueError: fact = ''
            if fact:
                self.progress.append(fact)
                await self.call.say('note', f'調べものの途中で分かったこと: {fact}')
            return json.dumps({'said': bool(fact)}, ensure_ascii=False)
        if name == 'web_search' and SEARCH == 'list':
            return await self._search(arguments)
        if name in direct_names():   # Dan's own tool, given whole: run as dan_tool runs it
            try: args = json.loads(arguments)
            except ValueError: args = {}
            name, arguments = 'dan_tool', json.dumps({'name': name, 'arguments': args}, ensure_ascii=False)
        from app.services.voice_sideband import execute_call
        run = execute_call({'type': 'function_call', 'call_id': item.call_id, 'name': name, 'arguments': arguments},
                           self.call.user_id, self.call.room_id, self.call.dialogue, self.call.record, self.id)
        if name != 'read_page':
            out = await run
        else:
            try:
                out = await asyncio.wait_for(run, READ_PAGE_S)
            except asyncio.TimeoutError:
                self.call.record('lookup_read_slow', lookup_id=self.id, seconds=READ_PAGE_S)
                return json.dumps({'error': f'このページは{READ_PAGE_S}秒で読めなかった。読めた他のページや検索の結果を使う。'}, ensure_ascii=False)
        self.verified.append((item.name, out['output']))
        if item.name in ('show_page_on_stage', 'compare_pages_on_stage'):
            try: self.shown += bool(json.loads(out['output']).get('shown'))
            except (ValueError, AttributeError): pass
        return out['output']


    async def _search(self, arguments):
        from app.services import web_search
        try: query = str(json.loads(arguments).get('query') or '').strip()
        except ValueError: query = ''
        if not query:
            return json.dumps({'error': 'query が空。'}, ensure_ascii=False)
        started = time.monotonic()
        found = await web_search.listing(query)
        out = json.dumps({'results': found['results']} if found['success'] else {'error': found['error']}, ensure_ascii=False)
        try:   # place names the speech model would misread get their reading, as every function's output does
            from app.services.voice_furigana import annotate_all
            out = json.dumps(annotate_all(json.loads(out)), ensure_ascii=False)
        except Exception:
            pass
        self.call.record('function_done', delegation_id=self.id, name='web_search', prefetched=False,
                         elapsed_ms=round((time.monotonic() - started) * 1000), output_chars=len(out))
        self.verified.append(('web_search', out))
        return out


REPEATABLE = ('web_search', 'read_page', 'places', 'page_clip', 'search_records')   # what a stuck lookup asks again


def _norm(arguments):
    try: value = json.loads(arguments or '{}')
    except ValueError: return str(arguments or '')
    return json.dumps(value, ensure_ascii=False, sort_keys=True).lower()


MARKUP = re.compile(r'<[｜|]{1,2}DSML[｜|]{1,2}tool_calls>.*?(</[｜|]{1,2}DSML[｜|]{1,2}tool_calls>|$)', re.S)


PARTS = re.compile(r'```(?:openui-lang|openui)\s*\n(.*?)(?:\n```|$)', re.S)


def split_parts(text):
    """The spoken answer and the parts block written after it (the last one), apart."""
    text = str(text or '')
    blocks = PARTS.findall(text)
    spoken = PARTS.sub('', text).strip()
    return spoken, (blocks[-1].strip() if blocks else '')


def without_markup(text):
    """The answer without a tool call DeepSeek may write into it as text: it would be read aloud as code."""
    return MARKUP.sub('', str(text or '')).strip()


def stateless():
    """DeepSeek keeps no responses: previous_response_id is refused (「No tool call found for tool output」)."""
    return MODEL.startswith('deepseek')


def _item(output):
    """One output item of a round (reasoning, function_call, message) as the next round's input."""
    if hasattr(output, 'model_dump'):
        return output.model_dump(exclude_none=True)
    return {k: v for k, v in vars(output).items() if v is not None}


def _client(model=None):
    """The connection for a model's company: this file's MODEL when none is named. The router's earlier backend names its own
    model (gpt-6-luna): on 2026-11-12 it was given this file's DeepSeek connection and every such request in a call was refused
    (「The supported API model names are deepseek-flash, deepseek-v4-pro, but you passed gpt-6-luna」)."""
    from openai import AsyncOpenAI
    from app.config import settings
    from app.services import inbox
    inbox._env()
    if (model or MODEL).startswith('deepseek'):
        return AsyncOpenAI(api_key=(os.environ.get('DEEPSEEK_API_KEY') or '').strip(), base_url='https://api.deepseek.com',
                           timeout=ROUND_TIMEOUT_S, max_retries=1)
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY or os.environ.get('OPENAI_API_KEY'), timeout=ROUND_TIMEOUT_S, max_retries=1)


class Call:
    """The background work of one call, and how it speaks into it."""
    def __init__(self, session_id, user_id, room_id, dialogue, send, record):
        self.session_id, self.user_id, self.room_id = session_id, user_id, room_id
        self.dialogue, self.send, self.record = dialogue, send, record
        self.lookups = {}
        self.closed = False
        self.router = None          # voice_router.Router of the call, when the requests are routed by Jev
        self._spec = None
        self.warming = None

    def spec(self):
        """The same instructions and tools for every round of every lookup of the call (the clock is the call's start), so
        the model's prompt cache holds them: the first round of a lookup read 12,000 tokens uncached (4.3 s), the next ones
        about 2-3 s."""
        if self._spec is None:
            self._spec = {'model': MODEL, 'instructions': instructions(), 'tools': tools(), 'tool_choice': 'auto', 'parallel_tool_calls': True,
                          'reasoning': {'effort': REASONING}, 'max_output_tokens': 8000}
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

    async def say(self, kind, text):
        """A fact into the call through its one entry (voice_say): what may be said as it is, without page addresses
        (「公式ページは https://revoluone.com/r630/」 was read out, 11/5 15:19). The whole answer, addresses too, stays in
        the lookup (status reads it; the stage and the earlier backend use it)."""
        if self.closed:
            return
        from app.services.voice_say import say
        try:
            said = await say(self.send, kind, text, self.record)
            self.record('lookup_spoken', chars=len(said))
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
        if not carried:
            # 「画面に出して」 after an answer started from nothing: the same three searches again, about 8 s before the first
            # page (2026-11-03 22:20 test call, weights_100kg). The last answered lookup of the call hands on what it found.
            answered = [l for l in self.lookups.values() if l.state == 'answered' and l.verified]
            if answered: carried = answered[-1].handover()
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
        """The call ended. A running lookup goes on and puts its answer in the room's chat (deliver): the owner who hung up
        after 2 min 27 s on 2026-11-12 22:44 still wanted the answer."""
        self.closed = True
        if self.warming is not None and not self.warming.done():
            self.warming.cancel()


_calls = {}
URL_TEXT = re.compile(r'\s*(?:\(|（)?https?://[^\s)）」』、。]+(?:\)|）)?')


def unspoken_urls(text):
    """The text without web addresses (and the 「は、」 left before one), for what is said aloud."""
    out = URL_TEXT.sub('', str(text or ''))
    return re.sub(r'[はが、:：\s]+(?=[。！？!?]|$)', '', out).strip()


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
