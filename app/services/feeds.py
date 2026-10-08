"""SNS and other pages Dan looks at for the user (inbox stage 2, owner 2026-10-02): "X も見といて" -> Dan adds the page where
that service lists what reached the user (notifications, messages). Every FEED_MINUTES the page is read in Dan's own
browser with the saved logins (feed_reader), a small model lists the items on it, and what was not there before goes into
the inbox like any mail (inbox.receive: the same judgement, the user's wishes, the same outlet). No code per service.

Kept in the one watch ledger (pending_followups, kind 'page', since 2026-10-08): spec = {service, url, seen: [keys],
digest, key_version, failures, told_login, until}; the ledger's poller looks every FEED_MINUTES and ends it at `until`.
The first look only learns what is already there.
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
KEY_VERSION = 3   # 2026-10-08: the seen-key comes from the page's own text (no longer from what the model wrote)
PAGE_DAYS = 30    # a page watch ends by itself after this unless `until` says otherwise
_running = asyncio.Lock()


_LEDGER_KEYS = ('id', 'room_id', 'note', 'user_id')


def _row_to_feed(watch):
    feed = dict(watch.get('spec') or {})
    feed.update(id=watch['id'], room_id=watch.get('room_id'), note=watch.get('plain_note') or '', user_id=watch.get('user_id'))
    return feed


def _feeds(user_id):
    """The user's page watches, from the watch ledger."""
    from app.services.followups import list_watches
    return [_row_to_feed(w) for w in list_watches() if w.get('kind') == 'page' and w.get('user_id') == user_id]


def _put(user_id, feed):
    """Save the watch's state and set its next look (later while the page keeps failing)."""
    from datetime import datetime, timedelta, timezone
    from app.services.followups import reschedule_watch
    spec = {k: v for k, v in feed.items() if k not in _LEDGER_KEYS}
    wait = FEED_MINUTES * 60 * (1 if int(feed.get('failures') or 0) < 3 else 4)
    reschedule_watch(feed['id'], 'page', feed.get('note') or '', spec, datetime.now(timezone.utc) + timedelta(seconds=wait))


def _drop(user_id, feed_id):
    from app.services.followups import cancel_watch
    return bool(feed_id) and cancel_watch(feed_id)


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
一覧に本人自身が送った最後のメッセージが出ている（「あなた:」「You:」など）なら mine を true にする。
JSONだけを返す: {"login_needed": false, "items": [{"who": "相手の名前やID", "kind": "DM|コメント|返信|メンション|通知", "text": "中身（ページの文字のまま短く）", "mine": false}]}"""


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


_AGO = re.compile(r'\d+\s*(分|時間|秒|日|週間)前?|\d+\s*[smhdw]\b|・')


def _anchor(item, page):
    """The page's own lines for an item: the line holding the start of its text and the line above it (usually who sent
    it). None when the text is not found as written."""
    head = re.sub(r'\s+', ' ', str(item.get('text') or '')).strip()[:16]
    if not page or len(head) < 2:
        return None
    lines = [re.sub(r'\s+', ' ', l).strip() for l in page.splitlines()]
    lines = [l for l in lines if l]
    for i, line in enumerate(lines):
        if head in line:
            return (lines[i - 1] if i else '') + '|' + line
    return None


def _key(feed, item, page=None):
    """Same item, same key on every look: made from the page's own text where the item stands (what a model writes down
    can change from look to look); who + text when the text is not on the page as written."""
    raw = _anchor(item, page) or (str(item.get('who') or '') + '|' + str(item.get('text') or '')[:60])
    raw = re.sub(r'\s+', ' ', _AGO.sub('', raw)).strip().lower()
    return hashlib.sha1((feed['id'] + '|' + raw).encode('utf-8')).hexdigest()[:16]


def _mine(item):
    """The user's own last message shown in a list, not something that reached them."""
    text = str(item.get('text') or '').lstrip()
    return bool(item.get('mine')) or text.startswith(('あなた:', 'あなた：', 'You:', 'You sent', '自分:'))


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
    if digest == feed.get('digest') and feed.get('key_version') == KEY_VERSION:   # an old-key feed learns on this look
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
    first = (not feed.get('seen') and not feed.get('digest')) or feed.get('key_version') != KEY_VERSION
    seen = [] if feed.get('key_version') != KEY_VERSION else list(feed.get('seen') or [])
    fresh = [i for i in found['items'] if _key(feed, i, text) not in seen]
    feed.update(digest=digest, failures=0, told_login=False, key_version=KEY_VERSION,
                seen=(seen + [_key(feed, i, text) for i in fresh])[-SEEN_KEEP:])
    fresh = [i for i in fresh if not _mine(i)]
    _put(user_id, feed)
    if first:
        return f'最初の1回: 今ある{len(found["items"])}件を見たことにした'
    for item in fresh[:10]:
        who, body = str(item.get('who') or '(不明)'), str(item.get('text') or '')
        try:
            await inbox.receive(user_id, feed['service'], who, body, subject=f'{feed["service"]} {item.get("kind") or ""}: {who}'.strip(),
                                source_id=f'feed:{feed["id"]}:{_key(feed, item, text)}', metadata={'feed': feed['id'], 'url': feed['url'], 'kind': item.get('kind'),
                                                                                       'watch_note': feed.get('note') or ''})
        except Exception:
            logger.exception('feeds: receive failed %s', feed['service'])
    return f'新しく{len(fresh)}件'


async def fire(row):
    """The ledger's poller: one page watch is due (row = the decoded ledger row). Past `until` it ends with one line."""
    from datetime import datetime, timezone
    from app.services import inbox
    from app.services.followups import mark_status
    feed = _row_to_feed(row)
    user_id = row.get('user_id') or ''
    until = str(feed.get('until') or '')
    if until and datetime.now(timezone.utc) >= datetime.fromisoformat(until.replace('Z', '+00:00')):
        mark_status(row['id'], 'done')
        await inbox.say(user_id, row.get('room_id'), f'{feed.get("service")}（{feed.get("url")}）の見回りは期限で終えました。続けるなら言ってください。', push=False)
        return
    async with _running:   # one browser look at a time
        try:
            result = await poll(user_id, feed)
            logger.info('feeds %s %s: %s', user_id[:8], feed.get('service'), result)
        except Exception:
            logger.exception('feeds: poll failed %s', feed.get('service'))
            _put(user_id, feed)


TOOL = {
    'name': 'feed',
    'description': ('本人が「X（Twitter）も見といて」「このインスタのアカウントの通知も見て」のように、SNS などで本人に届くものの見張りを頼んだら add する。'
                    'url は、そのサービスで本人あての通知や DM が並ぶページ（例: https://x.com/notifications 、https://x.com/messages 、'
                    'https://www.facebook.com/notifications ）。ダンのブラウザで保存済みのログインを使って15分おきに読み、新しく届いたものは'
                    'メールと同じ受け口（判断・本人の希望・チャットへの出し方）に入る。add するとその場で1回読み、今ある分は既読扱いにする'
                    '（結果にログインが要ると出たら、そのサイトのログイン情報を本人に聞いて save_credentials してから、もう一度 add する）。'
                    'list で見張り中の一覧、remove で止める。'
                    '特定の相手からの返事待ち（「◯◯さんから返信が来たら教えて」）には使わない。それは watch の reply_from（届いたら1回知らせて終わる）。'
                    '見張りには期限がある（until。省略時30日）。期限が来たら1行知らせて終わる。'),
    'input_schema': {'type': 'object', 'properties': {
        'action': {'type': 'string', 'enum': ['add', 'list', 'remove']},
        'service': {'type': 'string', 'description': 'add: サービス名（例: X、Facebook、LinkedIn）'},
        'url': {'type': 'string', 'description': 'add: 通知や DM が並ぶページの URL'},
        'note': {'type': 'string', 'description': 'add: 本人の言葉（何を見てほしいか）'},
        'until': {'type': 'string', 'description': 'add: いつまで見るか（日時。省略時30日）'},
        'id': {'type': 'string', 'description': 'remove: 止める見張りの id'},
    }, 'required': ['action'], 'additionalProperties': False},
}


async def tool(params, room_id=None):
    user_id = os.environ.get('DAN_USER_ID', '')
    if not user_id:
        return {'success': False, 'error': 'user unknown'}
    action = params.get('action')
    if action == 'add':
        from datetime import datetime, timedelta, timezone
        from app.services.followups import create_watch, list_watches
        url, service = str(params.get('url') or '').strip(), str(params.get('service') or '').strip()
        if not url.startswith('http') or not service:
            return {'success': False, 'error': 'service と http(s) の url が要る'}
        until = None
        if str(params.get('until') or '').strip():
            try:
                until = datetime.fromisoformat(str(params['until']).replace('Z', '+00:00'))
                until = until if until.tzinfo else until.replace(tzinfo=timezone(timedelta(hours=9)))
            except ValueError:
                return {'success': False, 'error': 'until は日時（例 2026-11-08T09:00）'}
        same = next((f for f in _feeds(user_id) if f['url'] == url), None)
        if same:
            feed = same
        else:
            made = create_watch(room_id or os.environ.get('DAN_SESSION_ID', ''), user_id, 'page',
                                str(params.get('note') or f'{service} に本人あてに届くものを見る')[:300], fire_at=until,
                                spec={'service': service, 'url': url, 'seen': [], 'key_version': KEY_VERSION})
            if not made.get('scheduled'):
                return {'success': False, 'error': made.get('message')}
            feed = _row_to_feed(next(w for w in list_watches() if w['id'] == made['id']))
        feed.update(digest='')
        result = await poll(user_id, feed)
        return {'success': True, 'output': f'{service} の見張りを{"更新" if same else "始めた"}（id {feed["id"]}、15分おき、期限 {str(feed.get("until") or "")[:10]}）。1回目: {result}'}
    if action == 'remove':
        return {'success': _drop(user_id, str(params.get('id') or '')), 'output': '止めた'}
    rows = _feeds(user_id)
    return {'success': True, 'output': '\n'.join(f'{f["id"]} {f["service"]} {f["url"]}（失敗{f.get("failures") or 0}回）' for f in rows) or '見張り中のページはない'}
