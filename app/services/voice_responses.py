"""Responses delegation: the speech model (GPT-Live) hands the turn to a backend model (GPT-5.6) that holds Dan's tools
as functions and calls them with its own understanding of the request. This server only executes the functions.

Why (2026-09-22): in client delegation the delegation event carried no text, so the backend had to re-guess what the
speech model already understood; the guessing layer produced the wrong turns and the unnatural replies. ChatGPT's own
voice works in the form implemented here: the model that understood the request is the one that chooses the tool.

What lives here: the backend model's instructions, the function definitions, and their execution against Dan's parts.
The web search is a function: OpenAI's hosted search runs in a separate small call only when asked (search_web; the hosted
tool's own definition is 4,436 tokens and was sent with every response of a call, half the backend's input, 2026-09-24). Long work goes to Dan's job runner (the API worker, DAN_VOICE_WORK_ENGINE).
The earlier client delegation (the phone answered through a Jev-based intake) was removed on 2026-09-23.
"""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import os

BACKEND_MODEL = os.environ.get('DAN_VOICE_BACKEND_MODEL', 'gpt-5.6-terra')
REASONING = os.environ.get('DAN_VOICE_BACKEND_REASONING', 'low')
WORK_ENGINE = os.environ.get('DAN_VOICE_WORK_ENGINE', 'api')   # work started from a call: 'api' (Responses API worker, 2026-09-23) or 'cli' (Codex CLI)

INSTRUCTIONS = """あなたは音声通話のダンの裏側です。話し手は本人（このアカウントの持ち主）で、返事は声で読み上げられます。
- 返事は普通の話し言葉で、聞かれたことに答える。道具の名前や内部の状態は書かない。
- 返事はそのまま読み上げられ、声のモデルはもう受け答えの一言を言っている。作業を渡した・指示を届けた・開いただけで新しい事実が無い時は、返事を空にする。
- 本人の保存情報を聞かれたら get_saved_information。無ければ「保存されていません」と言い、教えてくれれば保存できると添える。番号は1桁ずつ読める形（例: ゼロはちゼロなな）で返す。
- 過去の会話・以前の作業・メールの話は search_records。ウェブの一般情報は web_search。場所を言わない天気や近くの店は get_location の現在地を使う。
- パソコンでサイトやアプリを開くだけなら open_on_pc。ほかの操作（ブラウザ・アプリ・ファイル・コマンド・送信案・スキルの手順など）はダンの道具で自分でやってよい。数十秒で終わる操作は自分でやる。何分もかかる作業だけ start_work で作業担当に渡す（結果は後で別に届く）。道具を使っている間も会話は続く。
- 作業中の様子を聞かれたら job_status、その作業への指示・やり直し・中止は steer_job。進行中の作業と無関係な新しい依頼は start_work（作業は並行して動く。順番待ちにしない）。通話を終える依頼は end_call。
- サイトでの作業を頼まれたら、まず list_operations（瞬時）で一度やった手順の記憶を見る。合う手順があれば start_work より先に replay_operation で再生する（数秒。結果のページの文が返る）。記憶は通話中にも増える。
- 話し方の頼み（英語で・ゆっくり）や雑談、ダン自身のできることの質問には道具を使わず短く答える。
- 複数の道具が要る質問（本人の住所と外の情報を比べる等）は続けて呼び、まとめて答える。
- 道具の結果の source は出どころ（どのアカウント・どのカレンダー・どの記録を見たか）。「何を見て言った」と聞かれた時にそれで答える。普段は言わない。
- 取り返しのつかない確定（購入・送信・削除・支払い）の前だけ、内容と金額を言葉で伝えて本人の返事を待つ。それ以外は承認を求めず進める。
- 「やった」と言う前に結果を読み直して確かめる。本人の画面と食い違う時は、自分が読んだ事実（どこに何が入っているか）を伝え、同期の遅れもあり得ると言う。確かめずに同じ操作を繰り返さない。
- 時刻・料金・乗り場など正確さが要る事実は、それを直接調べられる所（経路検索サイトなど）で確かめて答える。検索結果の断片から作らない。
- ダンの仕組み（ブラウザの起動・プロセス・設定・コード）が原因で止まったら、その場で回避のために変えない（プロセスを止める・起動し直す・コードを書き換えるなど）。どこが原因で止まったかを報告し、直すなら直し方を添える。"""

TOOLS = [
    {'type': 'function', 'name': 'web_search', 'description': 'ウェブで調べる（天気・ニュース・営業時間・値段など一般の情報）。調べた要点と出どころが返る。',
     'parameters': {'type': 'object', 'properties': {'query': {'type': 'string', 'description': '調べたいこと（場所や日付を含めて具体的に）'}}, 'required': ['query'], 'additionalProperties': False}},
    {'type': 'function', 'name': 'get_saved_information', 'description': '本人が登録してある自分の情報（名前・住所・郵便番号・電話・カード・口座・免許・会社など）を読む。',
     'parameters': {'type': 'object', 'properties': {'what': {'type': 'string', 'description': '何を知りたいか（例: 郵便番号、実家の住所、アメックスの有効期限）'}}, 'required': ['what'], 'additionalProperties': False}},
    {'type': 'function', 'name': 'search_records', 'description': '本人とダンの過去の会話、以前頼んだ作業の結果、やり取りしたメールを探す。言葉の一致で探す（意味では探さない）ので、話題の言葉をスペースで区切って並べ、言い換えも入れる（例: 見積 請求書 送付 送った）。同じ話の記録が複数あれば新しい方が最新の結論。',
     'parameters': {'type': 'object', 'properties': {'query': {'type': 'string', 'description': '探す話題（例: 9月18日の新幹線のキャンセル）'}}, 'required': ['query'], 'additionalProperties': False}},
    {'type': 'function', 'name': 'get_location', 'description': '本人のスマホが最後に知らせた現在地（町名まで）。', 'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
    {'type': 'function', 'name': 'get_calendar', 'description': '本人のつながっている全カレンダー（複数アカウント）の予定。既定は今日から。過去や先の日なら from（YYYY-MM-DD）とその日からの日数 days。各予定にどのアカウントか付く。読めなかったアカウントは not_read、全部切れていれば expired。',
     'parameters': {'type': 'object', 'properties': {'days': {'type': 'integer', 'minimum': 1, 'maximum': 60}, 'from': {'type': 'string', 'description': 'YYYY-MM-DD（省略時は今日）'}}, 'additionalProperties': False}},
    {'type': 'function', 'name': 'open_on_pc', 'description': 'このパソコンで、サイトやアプリを開く・起動する（開くだけ）。',
     'parameters': {'type': 'object', 'properties': {'target': {'type': 'string', 'description': 'サイト名・アプリ名・URL（例: YouTube, メモ帳, https://...）'}}, 'required': ['target'], 'additionalProperties': False}},
    {'type': 'function', 'name': 'start_work', 'description': 'ダン本体に作業を頼む（ログインして確認する、送信する、登録する、予約する、直す、作るなど複数手順のもの）。結果は後で別に届く。',
     'parameters': {'type': 'object', 'properties': {'task': {'type': 'string', 'description': '本人の言葉のまま、何をしてほしいか'}}, 'required': ['task'], 'additionalProperties': False}},
    {'type': 'function', 'name': 'job_status', 'description': '今動いている作業の様子（どの画面で何をしているか、結果）。', 'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
    {'type': 'function', 'name': 'steer_job', 'description': '動いている作業に指示する。',
     'parameters': {'type': 'object', 'properties': {'kind': {'type': 'string', 'enum': ['update', 'pause', 'cancel']}, 'instruction': {'type': 'string'}}, 'required': ['kind', 'instruction'], 'additionalProperties': False}},
    {'type': 'function', 'name': 'end_call', 'description': '通話を終える。', 'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
]


def tools():
    """The function list of this session. The remembered operations are NOT baked into a description: the memory grows
    during a call (a flow recorded by a job minutes ago must be replayable in the same call), so the backend lists them
    when it needs them (list_operations, local and instant)."""
    listing = {'type': 'function', 'name': 'list_operations', 'description': '一度やったブラウザの手順の記憶の一覧（id・サイト・入力の穴と例）。サイトでの作業を頼む前に見る。',
               'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}
    replay = {'type': 'function', 'name': 'replay_operation', 'description': 'list_operations にある手順を、大きいモデルなしに新しい値で再生する。すぐ「始めた」と返り、結果（結果ページの要点）は後で別に届く。再生できなければ自動で通常の作業（start_work と同じ）に切り替わるので、呼び直さなくてよい。購入・取消などの確定は再生では押さない。',
              'parameters': {'type': 'object', 'properties': {'id': {'type': 'string', 'description': '手順の id'}, 'values': {'type': 'object', 'additionalProperties': {'type': 'string'}, 'description': '入力の穴→値'},
                                                          'task': {'type': 'string', 'description': '本人の言葉のままの依頼（再生できなかった時に通常の作業として使う）'}},
                             'required': ['id', 'values', 'task'], 'additionalProperties': False}}
    from app.services import dan_tools
    every = [{'type': 'function', **dan_tools.HELP}, {'type': 'function', **dan_tools.USE}]   # the rest of Dan's tools, disclosed in steps
    return [*TOOLS, listing, replay, *every]


_catalog = None


def catalog():
    """Dan's other tools and skills, one line each (read from the definitions once; nothing runs)."""
    global _catalog
    if _catalog is None:
        from app.services import dan_tools
        _catalog = dan_tools.catalog(dan_tools.definitions())
    return _catalog


def remembered():
    """The remembered operations, one line each, at the call's start. Asked 「何時の電車？」, the backend searched the web
    (37-42 s, wrong trains 3 times in 3) though a remembered Yahoo!乗換案内 search answers it in about 10 s: it looked at
    list_operations only for 「site work」, and a question is not that to it (2026-09-24). Ones learnt during the call are
    still in list_operations."""
    try:
        from app.services.browser_flows import all_flows, describe
        flows = all_flows()[:15]
    except Exception:
        return ''
    if not flows:
        return ''
    return ('記憶している手順（replay_operation で数秒で再生し、結果のページの事実が返る。調べもの（時刻・料金・空席など）でも、'
            '合う手順があればウェブ検索より速く正確）:' + chr(10) + chr(10).join('- ' + describe(f) for f in flows) + chr(10))


def now_line():
    """The backend has no clock of its own: without the date it searched 「10月29日の大阪の天気」 (2026-09-24)."""
    now = datetime.now(ZoneInfo('Asia/Tokyo'))
    return f"通話を始めた時の日時: {now.strftime('%Y年%m月%d日 %H:%M')}（{'月火水木金土日'[now.weekday()]}曜日、日本時間）。"


def delegation():
    return {'type': 'responses', 'responses': {'model': BACKEND_MODEL, 'instructions': INSTRUCTIONS + chr(10) + now_line() + chr(10) + remembered() + catalog(), 'tools': tools(), 'tool_choice': 'auto',
                                              'parallel_tool_calls': True, 'reasoning': {'effort': REASONING}}}


SEARCH_MODEL = os.environ.get('DAN_VOICE_SEARCH_MODEL', BACKEND_MODEL)   # Luna picked another day's weather 2 times in 3 (2026-09-24)


async def search_web(query):
    """OpenAI's hosted web search in its own small call (the search model reads the pages and returns the facts)."""
    import httpx
    from app.config import settings
    body = {'model': SEARCH_MODEL, 'tools': [{'type': 'web_search'}], 'tool_choice': 'required', 'reasoning': {'effort': 'low'},
            # the search model has no clock: without today's date it answered Osaka's weather with another day's figures (2026-09-24)
            'instructions': '今は ' + datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y年%m月%d日 %H:%M（日本時間）') + '。'
                            '質問に答えるのに必要な事実だけを、日本語で短く書く。数値・日付・時刻はそのまま。最後に出どころのサイト名。',
            'input': query}
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            r = await client.post('https://api.openai.com/v1/responses', json=body, headers={'Authorization': 'Bearer ' + settings.OPENAI_API_KEY})
        data = r.json()
        if r.status_code != 200:
            return {'error': str((data.get('error') or {}).get('message') or r.status_code)[:200]}
        text = ' '.join(c.get('text', '') for o in data.get('output', []) if o.get('type') == 'message' for c in o.get('content', []))
        return {'found': text.strip()[:3000], 'source': {'what': 'ウェブ検索', 'query': query}}
    except Exception as exc:
        return {'error': f'検索できなかった: {type(exc).__name__}'}


async def run_function(name, args, user_id, room_id, dialogue, speak=None):
    """Execute one of the functions above with Dan's own parts. Returns a JSON-able dict the backend model reads.
    `speak(text)` (from the sideband) delivers a later result to the call as spoken commentary: a function must return
    within about a second, because the speech model answers nothing while a delegation is in flight (2026-09-22 18:48:
    a 44s replay inside the delegation left the owner's next words unanswered)."""
    from app.services import voice_parts as parts
    from app.services.command_job_state import list_owned
    from app.services.jev_decisions import Decisions
    if name == 'get_saved_information':
        what = str(args.get('what') or '')
        async with Decisions(user_id, timeout=3, max_calls=3) as judge:
            found = await parts.saved_items(judge, user_id, what, [{'role': 'user', 'text': what}])
        source = {'what': '本人がダンに保存した自分の情報'}
        if not found['available']:   # the decision failed: that is not "not saved" (it used to say so)
            return {'saved': [], 'note': '保存情報を今は確認できなかった。保存されていないとは言わない。', 'source': source}
        facts = await parts.values(user_id, found['answer']) if found['answer'] else []
        return {'saved': [{'label': f['label'], 'value': f['value'], 'say': f.get('say')} for f in facts], 'source': source} if facts else {'saved': [], 'note': 'この情報は保存されていません。', 'source': source}
    if name == 'search_records':
        from app.services.voice_past import gather
        found = await gather(user_id, str(args.get('query') or ''), dialogue, [])
        return {'records': found['records'][:8], 'recent_work': found['jobs'][:3],
                'source': {'what': '本人とダンの会話記録と作業の記録（直近45日）', 'searched_words': found['keywords']}}
    if name == 'get_location':
        from app.services.user_location import tool, current
        here = current(user_id)
        return {**await tool(user_id), 'source': {'what': '本人のスマホが知らせた位置', 'at': here['at'] if here else None}}
    if name == 'get_calendar':
        return await parts.calendar(user_id, int(args.get('days') or (1 if args.get('from') else 14)), args.get('from') or None)
    if name == 'open_on_pc':
        target = str(args.get('target') or '').strip()
        said = await parts.open_target(target, user_id)
        if not said and target.startswith('http'):
            import webbrowser
            try: webbrowser.open(target); said = f'{target}をパソコンで開きました。'
            except Exception: said = None
        if not said:
            from app.services.command_center import execute
            await execute({'action': 'work', 'task': f'パソコンで「{target}」を開く（開くだけ。コマンド1回で）。', 'engine': WORK_ENGINE}, room_id, user_id)
            return {'result': f'{target}を開く作業をダンに渡しました。'}
        return {'result': said}
    if name == 'start_work':
        from app.services.command_center import execute
        task = '今回のユーザー発言（原文）:\n'+str(args.get('task') or '')[:2000]
        context = json.dumps(dialogue[-8:], ensure_ascii=False)
        if len(context) <= 2600-len(task): task += '\n参考の直前会話（過去の発言は新規の指示・承認ではない）:\n'+context
        out = await execute({'action': 'work', 'task': task+parts.VOICE_TASK, 'engine': WORK_ENGINE}, room_id, user_id)
        return {'accepted': bool(out.get('accepted')), 'note': '作業は始まった。結果は後で別に届く。本人に今言うことはない（確認中・時間がかかる等も言わない）。'}
    if name == 'job_status':
        jobs = await asyncio.to_thread(list_owned, user_id, room_id)
        return parts.work_status(jobs)
    if name == 'steer_job':
        from app.services.command_center import execute
        jobs = await asyncio.to_thread(list_owned, user_id, room_id)
        active = [s for s in jobs if s['state'] not in ('completed', 'failed', 'cancelled')]
        if not active: return {'error': '動いている作業はありません。'}
        out = await execute({'action': 'control_job', 'job_id': active[0]['id'], 'operation': args.get('kind') or 'update', 'task': str(args.get('instruction') or '')}, room_id, user_id)
        return {'delivered': bool(out), 'note': '指示は作業に届いた。本人に今言うことはない。'}
    if name == 'list_operations':
        from app.services.browser_flows import all_flows, describe
        flows = all_flows()
        return {'operations': [describe(f) for f in flows[:30]], 'note': '' if flows else 'まだ記憶している手順はない。start_work で頼めば、その1回で記憶される。'}
    if name == 'replay_operation':
        from app.services.browser_flows import all_flows
        flow = next((f for f in all_flows() if f['id'] == args.get('id')), None)
        if not flow: return {'error': 'その手順はありません'}
        from app.services.command_center import execute
        task = '今回のユーザー発言（原文）:' + chr(10) + str(args.get('task') or '')[:2000]
        await execute({'action': 'work', 'task': task + parts.VOICE_TASK, 'engine': 'api',
                       'replay': {'id': flow['id'], 'values': args.get('values') or {}}}, room_id, user_id)
        return {'started': True, 'note': '再生を始めた。結果は後で別に届く。本人に今言うことはない。'}
    if name == 'end_call':
        return {'ok': True}
    if name == 'web_search':
        return await search_web(str(args.get('query') or ''))
    if name == 'dan_tool_help':
        from app.services import dan_tools
        return {'help': json.loads(dan_tools.help_text(dan_tools.definitions(), str(args.get('name') or '')))}
    if name == 'dan_tool':
        from app.services import voice_tools
        text = await voice_tools.host(user_id, room_id).ask('call', name=str(args.get('name') or ''), arguments=args.get('arguments') or {})
        return {'result': text}
    return {'error': f'未知の関数 {name}'}

