"""lookup / wait_until: fixed forms of what Dan used to hand-write in throwaway Python.

One month of Claude-room logs: 1,530 inline Python snippets, 451 of them only to read
Dan's own data (mail, room history, outbound message cards, artifacts, watches, site
inquiries) with a 19% failure rate, and 2 hours spent in `sleep` polling a URL or a file.
Both tools live in the shared dan-tools layer so every model backend and voice-delegated
work get them. lookup is read-only and scoped to the calling user.
"""
import asyncio
import email
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from pathlib import Path

SOURCES = ('messages', 'mail', 'message_cards', 'artifacts', 'watches', 'inquiries', 'addresses')

LOOKUP_TOOL = {
    'name': 'lookup',
    'description': (
        'ダン自身が持っているデータを読む（読み取り専用）。Pythonを書いてDBやIMAPに直接つなぐ代わりに使う。'
        'source: messages=会話の履歴（room_id省略時はこの部屋。queryで全履歴をキーワード検索、無ければ新しい順。since/untilで期間）／'
        'mail=受信箱・送信済みのメール（mailbox: gmail, gmail2, icloud など。folder: inbox/sent。query, from_, to, since）／'
        'message_cards=外部宛メッセージの送信案カードと送信結果（status: pending/sent/discarded 等）／'
        'artifacts=登録済みの成果物と公開URL（room_id省略時は全部）／'
        'watches=見張り・続報の予約の詳細（room_id省略時はこの部屋。all_rooms=trueで全部屋）／'
        'inquiries=公開サイトのフォームに届いた問い合わせ（scope=サイトの識別子）／'
        'addresses=本人が使っているメールアドレスの一覧（どのサービスの登録に使っているか、ダンが受信箱を読めるか）。新規登録でどのアドレスを使うか本人に選んでもらう時に使う。'
        '本文は長いと切り詰める。id を指定すると1件を全文で返す（messages, mail, message_cards, inquiries）。'
    ),
    'input_schema': {'type': 'object', 'properties': {
        'source': {'type': 'string', 'enum': list(SOURCES)},
        'query': {'type': 'string', 'maxLength': 200, 'description': '探す言葉（messages は全履歴、mail は件名と本文）'},
        'room_id': {'type': 'string'}, 'all_rooms': {'type': 'boolean'},
        'id': {'type': 'string', 'description': '1件を全文で読む時の id（mail は一覧に出る uid）'},
        'since': {'type': 'string', 'description': 'ISO日時または日付（例 2026-09-01）'}, 'until': {'type': 'string'},
        'status': {'type': 'string'}, 'scope': {'type': 'string'},
        'mailbox': {'type': 'string'}, 'folder': {'type': 'string', 'enum': ['inbox', 'sent']},
        'from_': {'type': 'string'}, 'to': {'type': 'string'},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100},
    }, 'required': ['source'], 'additionalProperties': False},
}

WAIT_TOOL = {
    'name': 'wait_until',
    'description': (
        '条件が成り立つまで待って、成り立った瞬間に戻る。sleep を挟んで何度も確認する代わりに使う。'
        'url=そのURLが応答する（expect_status 既定200、text を指定すると本文に含まれるまで）／'
        'path=そのファイルやフォルダができる（stable=true で書き込みが止まるまで、min_bytes で最小サイズ）／'
        'path_gone=そのファイルが消える／port=そのポートが開く（closed=true で閉じる）。'
        'timeout_seconds 既定60・最大600。時間切れは success=false と最後に見えた状態を返す。'
    ),
    'input_schema': {'type': 'object', 'properties': {
        'url': {'type': 'string'}, 'expect_status': {'type': 'integer'}, 'text': {'type': 'string'},
        'path': {'type': 'string'}, 'stable': {'type': 'boolean'}, 'min_bytes': {'type': 'integer', 'minimum': 0},
        'path_gone': {'type': 'string'}, 'port': {'type': 'integer', 'minimum': 1, 'maximum': 65535}, 'closed': {'type': 'boolean'},
        'timeout_seconds': {'type': 'integer', 'minimum': 1, 'maximum': 600},
    }, 'additionalProperties': False},
}

CLIP = 600


def _clip(text, limit=CLIP):
    text = re.sub(r'\n{3,}', '\n\n', str(text or '')).strip()
    return text if len(text) <= limit else text[:limit]+f'…（全{len(text)}字。id 指定で全文）'


def _when(value):
    if not value:
        return None
    text = str(value).strip().replace('Z', '+00:00')
    # The database writes 5-digit fractions (…28.21366+00:00); Python 3.10 only reads 3 or 6.
    text = re.sub(r'\.(\d+)', lambda m: '.'+m.group(1)[:6].ljust(6, '0'), text, count=1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f'日時の形式が読めません: {text}（例 2026-09-01 または 2026-09-01T09:00:00+09:00）')
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=9)))  # the user's clock
    return parsed


def _result(title, rows, note=''):
    body = '\n\n'.join(rows) if rows else '（該当なし）'
    return {'success': True, 'count': len(rows), 'output': f'{title}: {len(rows)} 件{note}\n\n{body}'}


# ---- sources ---------------------------------------------------------------

async def _messages(p, user_id, room_id):
    from app.services.chat_service import ChatService
    chat = ChatService()
    room = p.get('room_id') or room_id
    if not room:
        raise ValueError('room_id が必要です（この部屋の id が分からない実行環境）')
    limit = p.get('limit', 30)
    since, until = _when(p.get('since')), _when(p.get('until'))
    if p.get('query'):
        rows = await chat.search_messages(room, user_id, p['query'], limit=limit)
    else:
        rows = await chat.get_messages(room, user_id, limit=100 if (since or until or p.get('id')) else limit)
    out = []
    for r in rows:
        try:
            created = _when(r.get('created_at'))
        except ValueError:
            created = None  # an unreadable stamp must not hide the message
        if p.get('id') and str(r.get('id')) != p['id']:
            continue
        if (since and created and created < since) or (until and created and created > until):
            continue
        who = r.get('sender_type') or r.get('role') or '?'
        text = r.get('content') or ''
        out.append(f"[{r.get('created_at', '')[:19]}] {who} (id={r.get('id')})\n{text if p.get('id') else _clip(text)}")
    return _result(f'会話の履歴 room={room}', out[:limit], '（古い範囲は since/until か query で絞る）' if len(rows) >= 100 else '')


def _decode(value):
    try:
        return str(make_header(decode_header(value or '')))
    except Exception:
        return value or ''


def _body(message):
    parts = list(message.walk()) if message.is_multipart() else [message]
    for wanted in ('text/plain', 'text/html'):
        for part in parts:
            if part.get_content_type() == wanted and 'attachment' not in str(part.get('Content-Disposition', '')):
                raw = part.get_payload(decode=True) or b''
                text = raw.decode(part.get_content_charset() or 'utf-8', errors='replace')
                return re.sub(r'<[^>]+>', ' ', text) if wanted == 'text/html' else text
    return ''


def _mail_sync(p):
    from app.services.imap_email_service import PROVIDERS, connect_mailbox
    box = p.get('mailbox') or next(iter(PROVIDERS))
    conn = connect_mailbox(box)
    try:
        folder = 'INBOX'
        if p.get('folder') == 'sent':
            _, boxes = conn.list()
            sent = [b.decode(errors='replace') for b in boxes or [] if '\\Sent' in b.decode(errors='replace')]
            folder = sent[0].split(' "/" ')[-1].strip() if sent else 'Sent'
        status, _ = conn.select(folder, readonly=True)
        if status != 'OK':
            raise RuntimeError(f'{box} の {folder} を開けません')
        if p.get('id'):
            _, data = conn.uid('fetch', p['id'], '(BODY.PEEK[])')
            message = email.message_from_bytes(data[0][1])
            return [f"From: {_decode(message.get('From'))}\nTo: {_decode(message.get('To'))}\nDate: {message.get('Date')}\n"
                    f"Subject: {_decode(message.get('Subject'))}\n\n{_body(message).strip()[:20000]}"], box, folder
        criteria = []
        since = _when(p.get('since')) or (datetime.now(timezone.utc)-timedelta(days=14))
        criteria += ['SINCE', since.strftime('%d-%b-%Y')]
        if p.get('from_'): criteria += ['FROM', f'"{p["from_"]}"']
        if p.get('to'): criteria += ['TO', f'"{p["to"]}"']
        charset = None
        if p.get('query'):
            criteria += ['TEXT', f'"{p["query"]}"']
            charset = 'UTF-8' if not p['query'].isascii() else None
        if charset:
            _, data = conn.uid('search', 'CHARSET', charset, *[c.encode('utf-8') if not c.isascii() else c for c in criteria])
        else:
            _, data = conn.uid('search', None, *criteria)
        uids = (data[0] or b'').split()[-(p.get('limit', 15)):]
        rows = []
        for uid in reversed(uids):
            _, fetched = conn.uid('fetch', uid, '(BODY.PEEK[HEADER.FIELDS (FROM TO DATE SUBJECT)] BODY.PEEK[TEXT]<0.1500>)')
            # Servers return the two requested parts in whatever order they like: tell them apart by their tag.
            header, preview = email.message_from_bytes(b''), ''
            for item in fetched:
                if not isinstance(item, tuple):
                    continue
                if b'HEADER' in item[0].upper():
                    header = email.message_from_bytes(item[1])
                else:
                    preview = item[1].decode('utf-8', errors='replace')
            preview = _clip(re.sub(r'<[^>]+>|=\r?\n', ' ', preview), 300)
            rows.append(f"uid={uid.decode()} | {header.get('Date', '')[:31]}\nFrom: {_decode(header.get('From'))} → To: {_decode(header.get('To'))}\n"
                        f"Subject: {_decode(header.get('Subject'))}\n{preview}")
        return rows, box, folder
    finally:
        try: conn.logout()
        except Exception: pass


async def _mail(p, user_id, room_id):
    rows, box, folder = await asyncio.to_thread(_mail_sync, p)
    return _result(f'メール {box}/{folder}', rows, '（既定は直近14日。本文は id=uid で全文）' if not p.get('id') else '')


async def _message_cards(p, user_id, room_id):
    from app.services.supabase_client import get_supabase_client
    def query():
        q = get_supabase_client().client.table('dan_proposals').select('*').eq('user_id', user_id)
        if p.get('id'): q = q.eq('id', p['id'])
        if p.get('status'): q = q.eq('status', p['status'])
        return q.order('created_at', desc=True).limit(p.get('limit', 15)).execute().data or []
    rows = await asyncio.to_thread(query)
    out = []
    for r in rows:
        data = r.get('action_data') or {}
        if p.get('query') and p['query'] not in json.dumps(r, ensure_ascii=False):
            continue
        body = data.get('body') or data.get('message') or r.get('description') or ''
        out.append(f"id={r.get('id')} | {r.get('type')} | status={r.get('status')} | {str(r.get('created_at'))[:19]}\n"
                   f"宛先: {data.get('to_name') or ''} {data.get('to') or ''} ({data.get('channel') or ''}) 件名: {data.get('subject') or r.get('title') or ''}\n"
                   f"{body if p.get('id') else _clip(body, 400)}")
    return _result('送信案カード', out)


async def _artifacts(p, user_id, room_id):
    from app.services.chat_artifact_service import ChatArtifactService
    rows = await ChatArtifactService().list(user_id, room_id=p.get('room_id'), limit=p.get('limit', 50))
    out = []
    for r in rows:
        if p.get('query') and p['query'].lower() not in json.dumps(r, ensure_ascii=False).lower():
            continue
        urls = {k: r[k] for k in ('shared_url', 'public_url', 'custom_domain', 'preview_url') if r.get(k)}
        out.append(f"id={r.get('id')} | {r.get('label') or r.get('slug')} | room={r.get('room_id')} | {str(r.get('created_at'))[:10]}\n{json.dumps(urls, ensure_ascii=False)}")
    return _result('成果物', out)


async def _watches(p, user_id, room_id):
    from app.services import followups
    rows = await asyncio.to_thread(followups.list_watches, None if p.get('all_rooms') else (p.get('room_id') or room_id))
    out = []
    for r in rows:
        spec = {k: v for k, v in (r.get('spec') or {}).items() if k != 'consecutive_errors'}
        out.append(f"id={r.get('id')} | kind={r.get('kind')} | 次回={r.get('fire_at')} | room={r.get('room_id')}\n"
                   f"{_clip(r.get('plain_note') or r.get('note'), 300)}\nspec: {json.dumps(spec, ensure_ascii=False)[:400]}")
    return _result('見張り・続報の予約', out[:p.get('limit', 50)])


async def _inquiries(p, user_id, room_id):
    from app.services.inquiry_service import InquiryService
    rows = await InquiryService().list(scope=p.get('scope'), limit=p.get('limit', 30))
    out = []
    for r in rows:
        if p.get('id') and str(r.get('id')) != p['id']:
            continue
        if p.get('query') and p['query'] not in json.dumps(r, ensure_ascii=False):
            continue
        fields = {k: v for k, v in r.items() if k not in ('id', 'scope', 'created_at', 'status') and v not in (None, '', {}, [])}
        text = json.dumps(fields, ensure_ascii=False)
        out.append(f"id={r.get('id')} | scope={r.get('scope')} | status={r.get('status')} | {str(r.get('created_at'))[:19]}\n{text if p.get('id') else _clip(text, 500)}")
    return _result('問い合わせ', out)


async def _addresses(p, user_id, room_id):
    """The owner's own mail addresses, for "which one shall I register with?". Addresses only, never a password."""
    from app.services.credentials_service import get_credentials_service
    from app.services.otp_service import get_otp_service
    service = get_credentials_service()
    used = {}
    for row in await service.list_credentials(user_id):
        name = row.get('service') or ''
        try: login = ((await service.get_credential(user_id, name)) or {}).get('id') or ''
        except Exception: login = ''
        if re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', login.strip()):
            if 'gserviceaccount' in login: continue   # a machine identity, not a mailbox
            used.setdefault(login.strip().lower(), []).append(name)
    rows = []
    for address, services in sorted(used.items(), key=lambda x: -len(x[1])):
        try: readable = await get_otp_service().has_imap_access(user_id, address)
        except Exception: readable = False
        rows.append(f"{address} — {len(services)}件の登録で使用（{', '.join(services[:6])}{' ほか' if len(services) > 6 else ''}）"
                    + (' ／ダンが受信箱を読める（確認メールやコードを自分で処理できる）' if readable else ' ／ダンは受信箱を読めない（確認メールは本人が見る必要がある）'))
    return _result('本人のメールアドレス', rows, '新規登録に使うアドレスとパスワードの決め方（自動生成して保存／本人が指定）は、必ず本人に確認する。')


async def lookup(params, user_id, room_id):
    source = params.get('source')
    handler = {'messages': _messages, 'mail': _mail, 'message_cards': _message_cards, 'artifacts': _artifacts,
               'watches': _watches, 'inquiries': _inquiries, 'addresses': _addresses}.get(source)
    if not handler:
        return {'success': False, 'error': 'source は '+' / '.join(SOURCES)+' のいずれか'}
    try:
        return await handler(params, user_id, room_id)
    except (ValueError, RuntimeError) as exc:
        return {'success': False, 'error': str(exc)}
    except Exception as exc:
        return {'success': False, 'error': f'{source} を読めませんでした: {type(exc).__name__}: {str(exc)[:200]}'}


# ---- wait_until ------------------------------------------------------------

async def wait_until(params):
    import socket
    import httpx
    kinds = [k for k in ('url', 'path', 'path_gone', 'port') if params.get(k)]
    if len(kinds) != 1:
        return {'success': False, 'error': 'url / path / path_gone / port のどれか1つを指定'}
    timeout = params.get('timeout_seconds', 60)
    if type(timeout) != int or not 1 <= timeout <= 600:
        return {'success': False, 'error': 'timeout_seconds は 1〜600'}
    kind = kinds[0]
    if kind == 'url' and not re.match(r'^https?://', params['url']):
        return {'success': False, 'error': 'url は http(s) のみ'}
    started = time.perf_counter(); seen = ''; size = None; interval = .25

    async def check():
        nonlocal seen, size
        if kind == 'url':
            try:
                async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
                    response = await client.get(params['url'])
                seen = f'HTTP {response.status_code}'
                return response.status_code == params.get('expect_status', 200) and (not params.get('text') or params['text'] in response.text)
            except httpx.HTTPError as exc:
                seen = type(exc).__name__
                return False
        if kind == 'port':
            with socket.socket() as s:
                s.settimeout(1)
                opened = s.connect_ex(('127.0.0.1', params['port'])) == 0
            seen = 'open' if opened else 'closed'
            return opened != bool(params.get('closed'))
        target = Path(os.path.expandvars(os.path.expanduser(params[kind])))
        if kind == 'path_gone':
            seen = 'exists' if target.exists() else 'gone'
            return not target.exists()
        if not target.exists():
            seen = 'missing'
            return False
        now = target.stat().st_size if target.is_file() else 0
        seen = f'{now} bytes'
        if now < params.get('min_bytes', 0):
            size = now
            return False
        if params.get('stable') and target.is_file():
            steady = size == now
            size = now
            return steady
        return True

    while True:
        if await check():
            return {'success': True, 'output': f'条件成立（{seen}）。待ち時間 {time.perf_counter()-started:.1f}秒'}
        if time.perf_counter()-started >= timeout:
            return {'success': False, 'error': f'{timeout}秒待っても成立しませんでした。最後の状態: {seen}'}
        await asyncio.sleep(interval)
        interval = min(interval*1.5, 2.0)
