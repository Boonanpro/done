"""SNS and other pages Dan looks at for the user (inbox stage 2, owner 2026-10-02): "X も見といて" -> Dan adds the page where
that service lists what reached the user (notifications, messages). Every FEED_MINUTES the page is read in Dan's own
browser with the saved logins (feed_reader), a small model lists the items on it, and what was not there before goes into
the inbox like any mail (inbox.receive: the same judgement, the user's wishes, the same outlet). No code per service.

Kept with the user's inbox settings (encrypted, per user): feeds = [{id, service, url, note, seen: [keys], digest,
last_at, failures, told_login}]. The first look only learns what is already there.
"""
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)
FEED_MINUTES = 15
SEEN_KEEP = 300
_running = asyncio.Lock()


def _feeds(user_id):
    from app.services import inbox
    return list(inbox.settings(user_id).get('feeds') or [])


def _put(user_id, feed):
    from app.services import inbox
    with inbox._lock:
        data = inbox.settings(user_id)
        rows = [f for f in data.get('feeds') or [] if f['id'] != feed['id']]
        data['feeds'] = rows + ([feed] if feed else [])
        inbox.save(user_id, data)


def _drop(user_id, feed_id):
    from app.services import inbox
    with inbox._lock:
        data = inbox.settings(user_id); before = len(data.get('feeds') or [])
        data['feeds'] = [f for f in data.get('feeds') or [] if f['id'] != feed_id]
        inbox.save(user_id, data)
    return before != len(data['feeds'])


def _browser_room(user_id):
    return 'feeds-' + user_id[:8]


async def _read(user_id, url):
    """The page's text, read in the feed's own browser room (a subprocess, as Dan's jobs use the browser)."""
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, 'DAN_USER_ID': user_id, 'DAN_SESSION_ID': _browser_room(user_id), 'DAN_BROWSER_ROOM': _browser_room(user_id),
           'DAN_BROWSER_HEADLESS': '1', 'DAN_BROWSER_OBSERVATION': 'dom', 'DAN_CORE_PORT': os.environ.get('DAN_CORE_PORT', '9000'),
           'PYTHONIOENCODING': 'utf-8'}
    creation = 0x08000000 if os.name == 'nt' else 0   # CREATE_NO_WINDOW: never a console window
    process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'app.services.feed_reader', url, cwd=str(root), env=env,
                                                   stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, creationflags=creation)
    try:
        out, _ = await asyncio.wait_for(process.communicate(), timeout=150)
    except asyncio.TimeoutError:
        process.kill()
        return {'ok': False, 'error': 'timeout'}
    lines = [l for l in out.decode('utf-8', 'ignore').splitlines() if l.startswith('{')]
    try:
        return json.loads(lines[-1])
    except Exception:
        return {'ok': False, 'error': 'no result'}


EXTRACT = """ページの文字から、本人あてに届いたもの（メッセージ・DM・コメント・返信・メンション・フォロー・いいね などの通知）を、見えている順に最大30件取り出す。
広告・おすすめ・ナビゲーションの文字・本人自身の投稿は含めない。
ログイン画面や「ログインしてください」の画面なら login_needed を true にする。
JSONだけを返す: {"login_needed": false, "items": [{"who": "相手の名前やID", "kind": "DM|コメント|返信|メンション|通知", "text": "中身（短く）", "key": "相手と中身の頭から作る、同じものなら毎回同じになる短い文字列"}]}"""


async def _extract(service, text):
    from app.services import api_job_providers, inbox
    inbox._env()
    provider = api_job_providers.make(os.environ.get('DAN_INBOX_MODEL') or os.environ.get('DAN_API_JOB_MODEL', 'deepseek-flash'))
    provider.start(EXTRACT, [], [f'サービス: {service}\nページ:\n{text[:8000]}'])
    step = await provider.step()
    try:
        data = json.loads(re.search(r'\{.*\}', step['text'], re.S).group(0))
    except Exception:
        return None
    items = [i for i in data.get('items') or [] if isinstance(i, dict) and (i.get('text') or i.get('who'))]
    return {'login_needed': bool(data.get('login_needed')), 'items': items}


def _key(feed, item):
    raw = str(item.get('key') or '') or (str(item.get('who') or '') + '|' + str(item.get('text') or '')[:40])
    return hashlib.sha1((feed['id'] + '|' + re.sub(r'\s+', ' ', raw).strip().lower()).encode('utf-8')).hexdigest()[:16]


async def poll(user_id, feed):
    """One look. Returns a short description of what happened (for the tool's answer and the log)."""
    from app.services import inbox
    feed = {**feed, 'last_at': time.time()}
    page = await _read(user_id, feed['url'])
    text = page.get('text') or ''
    if not page.get('ok') or not text.strip():
        feed['failures'] = int(feed.get('failures') or 0) + 1
        _put(user_id, feed)
        return f'読めなかった（{page.get("error") or (page.get("open") or {}).get("error") or "空"}）'
    digest = hashlib.sha1(re.sub(r'\d+\s*(分|時間|秒|日)前?|\d+[smhd]\b', '', text).encode('utf-8')).hexdigest()
    if digest == feed.get('digest'):
        feed['failures'] = 0
        _put(user_id, feed)
        return '変化なし'
    found = await _extract(feed['service'], text)
    if found is None:
        _put(user_id, feed)
        return '読み取れなかった'
    if found['login_needed']:
        feed['failures'] = int(feed.get('failures') or 0) + 1
        if not feed.get('told_login'):
            feed['told_login'] = True
            await inbox.say(user_id, None, f'{feed["service"]}（{feed["url"]}）を見ようとしたらログインが要りました。保存済みのログインで入れないので、'
                                           f'ログイン情報を教えてもらえればダンが入って、見張りを続けます。')
        _put(user_id, feed)
        return 'ログインが要る'
    first = not feed.get('seen') and not feed.get('digest')
    seen = list(feed.get('seen') or [])
    fresh = [i for i in found['items'] if _key(feed, i) not in seen]
    feed.update(digest=digest, failures=0, told_login=False, seen=(seen + [_key(feed, i) for i in fresh])[-SEEN_KEEP:])
    _put(user_id, feed)
    if first:
        return f'最初の1回: 今ある{len(found["items"])}件を見たことにした'
    for item in fresh[:10]:
        who, body = str(item.get('who') or '(不明)'), str(item.get('text') or '')
        try:
            await inbox.receive(user_id, feed['service'], who, body, subject=f'{feed["service"]} {item.get("kind") or ""}: {who}'.strip(),
                                source_id=f'feed:{feed["id"]}:{_key(feed, item)}', metadata={'feed': feed['id'], 'url': feed['url'], 'kind': item.get('kind')})
        except Exception:
            logger.exception('feeds: receive failed %s', feed['service'])
    return f'新しく{len(fresh)}件'


async def cycle_all():
    """Every user's feeds that are due, one at a time (called on the mail poller's tick)."""
    if _running.locked():
        return
    from app.services import inbox
    async with _running:
        for user_id in inbox.users():
            for feed in _feeds(user_id):
                wait = FEED_MINUTES * 60 * (1 if int(feed.get('failures') or 0) < 3 else 4)   # a failing page is looked at less
                if time.time() - float(feed.get('last_at') or 0) < wait:
                    continue
                try:
                    result = await poll(user_id, feed)
                    logger.info('feeds %s %s: %s', user_id[:8], feed['service'], result)
                except Exception:
                    logger.exception('feeds: poll failed %s', feed.get('service'))


TOOL = {
    'name': 'feed',
    'description': ('本人が「X（Twitter）も見といて」「このインスタのアカウントの通知も見て」のように、SNS などで本人に届くものの見張りを頼んだら add する。'
                    'url は、そのサービスで本人あての通知や DM が並ぶページ（例: https://x.com/notifications 、https://x.com/messages 、'
                    'https://www.facebook.com/notifications ）。ダンのブラウザで保存済みのログインを使って15分おきに読み、新しく届いたものは'
                    'メールと同じ受け口（判断・本人の希望・チャットへの出し方）に入る。add するとその場で1回読み、今ある分は既読扱いにする'
                    '（結果にログインが要ると出たら、そのサイトのログイン情報を本人に聞いて save_credentials してから、もう一度 add する）。'
                    'list で見張り中の一覧、remove で止める。'),
    'input_schema': {'type': 'object', 'properties': {
        'action': {'type': 'string', 'enum': ['add', 'list', 'remove']},
        'service': {'type': 'string', 'description': 'add: サービス名（例: X、Facebook、LinkedIn）'},
        'url': {'type': 'string', 'description': 'add: 通知や DM が並ぶページの URL'},
        'note': {'type': 'string', 'description': 'add: 本人の言葉（何を見てほしいか）'},
        'id': {'type': 'string', 'description': 'remove: 止める見張りの id'},
    }, 'required': ['action'], 'additionalProperties': False},
}


async def tool(params):
    user_id = os.environ.get('DAN_USER_ID', '')
    if not user_id:
        return {'success': False, 'error': 'user unknown'}
    action = params.get('action')
    if action == 'add':
        url, service = str(params.get('url') or '').strip(), str(params.get('service') or '').strip()
        if not url.startswith('http') or not service:
            return {'success': False, 'error': 'service と http(s) の url が要る'}
        same = next((f for f in _feeds(user_id) if f['url'] == url), None)
        feed = same or {'id': uuid.uuid4().hex[:8], 'service': service, 'url': url, 'note': str(params.get('note') or '')[:300], 'seen': []}
        feed.update(digest='', last_at=0)
        _put(user_id, feed)
        result = await poll(user_id, feed)
        return {'success': True, 'output': f'{service} の見張りを{"更新" if same else "始めた"}（id {feed["id"]}、15分おき）。1回目: {result}'}
    if action == 'remove':
        return {'success': _drop(user_id, str(params.get('id') or '')), 'output': '止めた'}
    rows = _feeds(user_id)
    return {'success': True, 'output': '\n'.join(f'{f["id"]} {f["service"]} {f["url"]}（失敗{f.get("failures") or 0}回）' for f in rows) or '見張り中のページはない'}
