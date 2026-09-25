"""The parts the phone voice uses (voice_responses): saved information, calendar, opening things on the PC, the state of
the work in progress, and the rules handed to voice-started work. Taken out of the old intake modules (voice_intake,
voice_intake2, voice_intake3), which answered the call through a Jev-based entrance and were retired on 2026-09-23 once
the backend model chose the tools itself (Responses delegation).
"""
import asyncio
import re

HERE = '__current_place__'
BAR = .6
VOICE_TASK = ('\n音声通話からの依頼です。報告は声で読み上げられるので、短く、新しく分かった事実だけを書く（同じ説明や謝罪をくり返さない）。'
              '見るだけの操作（ログイン、履歴・明細・状況の表示）は承認を求めずに進める。承認が要るのは購入・取消・送信など取り返しのつかない確定だけ。'
              '新規登録をする時は、使うメールアドレス（lookup の source=addresses で本人のアドレス一覧を出す）とパスワードの決め方を、始める前に本人に確認する。')

STATE_WORDS = {'queued': 'これから始める', 'running': '作業中', 'paused': '一時停止中', 'awaiting_confirmation': '本人の承認待ち',
               'completed': '完了', 'failed': '失敗', 'cancelled': '中止'}
DOING = {'open': 'ページを開いている', 'open_target': 'ページを開いている', 'click': '画面のボタンやリンクを押している', 'human_click': '画面を押している',
         'type': '文字を入力している', 'fill_form': 'フォームに入力している', 'fill_credential': 'ログイン情報を入力している', 'fill_totp_code': '認証コードを入力している',
         'wait_for_otp_from_app': '認証コードが届くのを待っている', 'wait_for_link_from_app': '確認メールのリンクを待っている', 'solve_captcha': 'ロボット確認を解いている',
         'follow': '画面をたどっている', 'read': '画面を読んでいる', 'find': '画面の中を探している', 'content': '画面を読んでいる', 'screenshot': '画面を見ている',
         'scroll': '画面を送っている', 'lookup': 'ダンの記録を調べている', 'read_url': 'ウェブのページを読んでいる', 'get_personal_info': '保存情報を確認している',
         'get_credentials': 'ログイン情報を確認している', 'remember_personal_info': '情報を保存している', 'web_search': 'ウェブで調べている',
         'desktop': 'PCのアプリを操作している', 'get_location': '現在地を確認している'}


def where_it_is(job):
    """The page the job's browser is on and what it is doing there, from what the tool layer recorded (not the model's notes)."""
    tool = job.get('current_tool') or job.get('last_tool') or {}
    doing = DOING.get(tool.get('action') or tool.get('name') or '', '')
    text = str((job.get('last_observation') or {}).get('text') or '')
    url = re.search(r'URL:\s*(\S+)', text); title = re.search(r'タイトル:\s*([^\n]{1,60})', text)
    host = re.sub(r'^https?://(www\.)?([^/]+).*$', r'\2', url.group(1)) if url else ''
    page = f"「{title.group(1).strip()}」（{host}）" if title and title.group(1).strip() else host
    if job.get('current_tool') and doing: doing = '今' + doing
    elif doing: doing = '直前に' + doing.replace('いる', 'いた')
    return '、'.join(x for x in (f'ブラウザは{page}を開いている' if page else '', doing) if x)


def work_status(jobs):
    """What Dan is doing right now, from the job files on this machine, in a few hundred characters."""
    rows = []
    for s in list(jobs)[:3]:
        events = s.get('events', [])
        rows.append({'依頼': s.get('task', '').split('参考の直前会話')[0].replace('今回のユーザー発言（原文）:', '').strip()[:160],
                     '状態': STATE_WORDS.get(s.get('state'), s.get('state')),
                     '今やっていること': next((e['text'][:200] for e in reversed(events) if e.get('kind') == 'progress'), '') if s.get('state') in ('running', 'queued') else '',
                     '今の画面と操作': where_it_is(s) if s.get('state') in ('running', 'queued', 'awaiting_confirmation', 'paused') else '',
                     '承認を待っている内容': ((s.get('confirmation') or {}).get('summary') or '')[:300],
                     '結果': str(s.get('result') or '')[:600]})
    return {'work_status': rows, 'note': 'これがダンの作業の今の状況の全部。聞かれたことに、この中から一言二言で答える。'
            '道具の名前や「確認待ち」などの内部の言葉はそのまま読まず、普通の言葉に言い換える。作業が無ければ「今は何も作業していません」。'}


async def calendar(user_id, days=14):
    """The owner's coming events. {'events': [...], 'source'} | {'expired': True} | {} when not connected."""
    from app.services.calendar_service import get_calendar_service
    try:
        read = await asyncio.wait_for(asyncio.to_thread(get_calendar_service().get_events_with_source, user_id, days), 12)
    except Exception as exc:
        return {'expired': True} if 'invalid_grant' in str(exc) or 'expired or revoked' in str(exc) else {}
    events = read['events']
    source = read.get('source') or {}
    if events and isinstance(events[0], dict) and events[0].get('error'):
        return {'expired': True, 'not_read': source['failed']} if source.get('failed') else {}
    out = {'events': [{k: e.get(k) for k in ('title', 'summary', 'start', 'end', 'location', 'calendar', 'account', 'id') if e.get(k)} for e in events[:30]],
           'source': {'what': 'つながっているカレンダー（全アカウント）', 'accounts': [a['account'] for a in source.get('accounts', [])],
                      'calendars': source.get('calendars', []), 'days': days}}
    if source.get('failed'):   # one account's login ran out: say so, the others were still read
        out['not_read'] = source['failed']
    return out


SITES = {'youtube': 'https://www.youtube.com/', 'ユーチューブ': 'https://www.youtube.com/', 'google': 'https://www.google.com/', 'グーグル': 'https://www.google.com/',
         'gmail': 'https://mail.google.com/', 'ジーメール': 'https://mail.google.com/', 'カレンダー': 'https://calendar.google.com/', 'amazon': 'https://www.amazon.co.jp/',
         'アマゾン': 'https://www.amazon.co.jp/', '楽天': 'https://www.rakuten.co.jp/', 'x': 'https://x.com/', 'twitter': 'https://x.com/', 'ツイッター': 'https://x.com/',
         'chatgpt': 'https://chatgpt.com/', 'インスタ': 'https://www.instagram.com/', 'instagram': 'https://www.instagram.com/', 'ダン': 'https://dan.paina.info/'}
APPS = {'メモ帳': 'notepad', '電卓': 'calc', 'エクスプローラー': 'explorer', 'エクスプローラ': 'explorer', '設定': 'ms-settings:', 'ペイント': 'mspaint',
        'discord': 'discord:', 'ディスコード': 'discord:', 'line': 'line:', 'ライン': 'line:', 'chrome': 'chrome', 'クローム': 'chrome', 'ブラウザ': 'https://www.google.com/'}


def targets():
    """One option per thing to open; its aliases go into the description so they do not split Jev's probability."""
    by_target = {}
    for name, target in list(SITES.items()) + list(APPS.items()):
        by_target.setdefault(target, []).append(name)
    return {names[0]: 'を開く（' + '／'.join(names) + '）' for names in by_target.values()}


def _launch(name):
    import os, webbrowser
    target = SITES.get(name) or APPS.get(name)
    if not target: return None
    try:
        if target.startswith('http'): webbrowser.open(target)
        else: os.startfile(target)
    except Exception:
        return None
    return f'{name}をパソコンで開きました。'


async def open_target(name, user_id=None):
    """Open a known site or app. The exact name first; otherwise Jev picks among the known targets (「ユーチューブ開いて」
    「アマゾンのページ」): a fixed choice among candidates is Jev's job, and a miss here used to start a whole job."""
    said = _launch(name) or _launch(name.lower())
    if said or not user_id: return said
    from app.services.jev_decisions import Decisions
    options = {**targets(), 'none': 'どれでもない（一覧にないサイトやアプリ）'}
    async with Decisions(user_id, timeout=1.5, max_calls=1) as judge:
        decision = await judge.choose({'request': name}, {'target': {'type': 'choice', 'criteria': options,
                                                                      'instructions': '頼まれた開く対象に当たるものを選ぶ。当たらなければ none。'}})
    answer = (decision.get('answers') or {}).get('target') or {}
    choice = answer.get('choice')
    if decision.get('available') and choice and choice != 'none' and (answer.get('probabilities') or {}).get(choice, 0) >= .8:
        return _launch(choice)
    return None


async def saved_items(judge, user_id, utterance, dialogue):
    """Which saved items are the answer, and which are only an ingredient (「うち」-> the home address). Jev sees item names
    only. Returns {'available', 'answer', 'ingredient', 'here', 'sensitive', 'direct'}; 'available' False means the
    decision could not be made (not that nothing is saved)."""
    from app.services.personal_info_service import PersonalInfoService
    empty = {'available': True, 'answer': [], 'ingredient': [], 'here': False, 'sensitive': False, 'direct': False}
    service = PersonalInfoService()
    try: rows = await asyncio.to_thread(service.list_masked_sync, user_id)
    except Exception: return {**empty, 'available': False}
    rows = [r for r in rows if r.get('field_key')][:120]
    if not rows: return empty
    names = {r['field_key']: f"{(r.get('label') or r['field_key'])[:100]}（{r['field_key']}）" for r in rows}
    kind = {r['field_key']: r.get('category') for r in rows}
    decision = await judge.choose({'question': utterance, 'recent_dialogue': dialogue}, {
        'answer': {'type': 'choice', 'criteria': {**names, 'none': '保存済みの項目は答えにならない。'},
                   'instructions': '最新の発言が求めている情報と同じものを指す保存項目、またはその情報を中に含む保存項目（町名や番地なら住所、市外局番なら電話番号）を選ぶ。対象そのものが違うもの（実家の住所を聞かれて自宅の住所、会社の電話を聞かれて個人の電話）は選ばず none。会話の続き（「その次は」「全部言って」）なら話題の項目を選ぶ。'},
        'ingredient': {'type': 'choice', 'criteria': {**names, HERE: '本人が今いる場所（「この近く」「ここから」、場所を言わない天気や店）。', 'none': '本人の保存項目は材料にならない。'},
                       'instructions': '答えを出す材料として必要な本人の保存項目を選ぶ。「うち」「自宅」は自宅の住所、「うちの会社」は会社の情報。'}})
    if not decision.get('available'): return {**empty, 'available': False}
    direct = {}

    def pick(question, related=False):
        probabilities = decision['answers'].get(question, {}).get('probabilities') or {}
        mass = {}
        for key, p in probabilities.items():
            if key in kind: mass[kind[key]] = mass.get(kind[key], 0) + p
        best = max(mass, key=mass.get) if mass else None
        if best and mass[best] >= BAR:   # the same fact is saved under several keys: judge by kind
            keys = sorted((k for k in probabilities if kind.get(k) == best), key=lambda k: -probabilities[k])
            direct[question] = True
            return [k for i, k in enumerate(keys[:3]) if i == 0 or probabilities[k] >= .1]
        if probabilities.get('none', 1) < .2:   # sure SOME item answers, split across kinds: take the top ones
            keys = sorted((k for k, v in probabilities.items() if k in kind and v >= .15), key=lambda k: -probabilities[k])[:3]
            if keys:
                direct[question] = True
                return keys
        if related and best == 'other':   # a name spread over items (family + given + kana)
            keys = sorted((k for k, p in probabilities.items() if kind.get(k) == best and p >= .04), key=lambda k: -probabilities[k])[:3]
            return keys if sum(probabilities[k] for k in keys) >= .2 else []
        return []
    answer = pick('answer', related=True)
    return {'available': True, 'answer': answer, 'ingredient': pick('ingredient'), 'direct': direct.get('answer', False),
            'here': (decision['answers'].get('ingredient', {}).get('probabilities') or {}).get(HERE, 0) >= BAR,
            'sensitive': any(kind.get(k) in ('payment', 'identity') for k in answer)}


async def values(user_id, keys):
    from app.services.personal_info_service import PersonalInfoService
    from app.services.voice_readings import annotate
    service, facts = PersonalInfoService(), []
    for key in keys[:3]:
        found = await service.get(user_id, key)
        if found and found.get('value'): facts.append({'label': found.get('label') or key, 'value': str(found['value'])[:500]})
    return annotate(facts)
