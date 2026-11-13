"""「〇〇さんから連絡来てる？」 for every place a person reaches the owner, read directly and fast (read only, 2026-11-13).

Why: the owner said 「APIで早く正確になるものは積極的に取り入れて良い」「正確なまま早くする必要がある」. Chatwork was read
through its API from 11/13 (chatwork_read); mail and LINE still went to chat Dan, who opened them in the browser or on the
phone (minutes). Here:

- mail: the three mailboxes Dan already reads over IMAP (gmail=shub6923, gmail2=0aw325171, icloud), side by side, headers of
  the last days, the person mails opened for their text without the quoted part, and the owner's sent folder to tell
  whether he answered. About 2.5 s for all three.
- LINE official accounts: every message their webhooks received is kept already (Cloudflare D1 itsuki-line: イツキ main, VIP,
  ふくろうP; the ポルノアンチ artifact's sqlite). About 0.3 s.
- personal LINE: the notifications on the Galaxy (line_notices), now and as recorded. About 0.6 s.

Nothing here sends, marks as read or opens a screen. Replies stay with the outbound card after the owner's approval.
"""
import asyncio
import email
import json
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.services.chatwork_read import found_in, norm, words

JST = ZoneInfo('Asia/Tokyo')
MAIL_DAYS = 7
MAIL_HEADERS = 120          # newest mails per mailbox looked at
DEEP_DAYS = 120             # a named person not in the last days: searched this far back
DEEP_SCAN = 500             # senders read here when the server's search finds nobody
BODY_BYTES = 60000          # of a mail's text: a mail with attachments is megabytes
PICK = 6                    # person mails opened per mailbox
TEXT = 600
CACHE_S = 30
D1 = ('https://api.cloudflare.com/client/v4/accounts/a68afab25fafe65037318fb691bbd9d5'
      '/d1/database/df75bf51-2896-4719-9045-3894a4d2ac75/query')
D1_CREDENTIAL = 'cloudflare_api_token_workers'
CHANNELS = {'main': '投手コーチイツキの公式LINE', 'vip': '【VIP限定】イツキの公式LINE', 'fukurou': 'ふくろうPの公式LINE'}
PORNANTI_DB = Path.home()/'.dan/workspace/data/pornanti-feedback.sqlite3'
AUTO = re.compile(r'no-?reply|donotreply|do-not-reply|notif|notice|newsletter|mailer-daemon|postmaster|post_master|bounce|'
                  r'mktg|magazine|marketing|promo|campaign|^news@|^info@chat-work\.com$|@docs\.google\.com$|@github\.com$', re.I)
QUOTE = re.compile(r'^[ \t]*(>|On .{4,80} wrote:|\d{4}年\d{1,2}月\d{1,2}日.{0,60}(書きました|wrote)|-{2,} ?(Original|Forwarded|転送)|'
                   r'差出人[:：]|From: )', re.M)
_cache = {}
_pool = {}                  # mailbox -> (connection, last used)
_pool_lock = threading.Lock()
POOL_S = 20 * 60


def when(moment):
    if isinstance(moment, (int, float)):
        moment = datetime.fromtimestamp(moment, JST)
    moment = moment.astimezone(JST)
    return f'{moment.month}月{moment.day}日 {moment.hour}:{moment.minute:02d}'


def _clip(text, limit=TEXT):
    text = re.sub(r'[ \t　]+', ' ', re.sub(r'\n\s*\n+', '\n', str(text or ''))).strip()
    return text if len(text) <= limit else text[:limit] + f'…（全{len(text)}字）'


# ---- mail -----------------------------------------------------------------------------------------------------------------

def _decode(value):
    from app.services.dan_lookup import _decode as decode
    return decode(value)


def automated(address, headers):
    """A notice, a newsletter or a machine's mail, not a person writing to the owner. A person's mail comes back to the
    sender's own address; a sending service puts a bounce address of its own in Return-Path (SES, SendGrid, bounce.*),
    and big senders add Feedback-ID (seen 11/13 on Amazon, X, Tesla, 楽天; not on 税理士・DisplayModule)."""
    if AUTO.search(address or ''):
        return True
    back = parseaddr(headers.get('Return-Path') or '')[1].lower()
    if headers.get('Feedback-ID') or (back and address and back != address):
        return True
    if headers.get('List-Unsubscribe') or headers.get('List-Id'):
        return True
    if (headers.get('Precedence') or '').strip().lower() in ('bulk', 'list', 'junk'):
        return True
    return (headers.get('Auto-Submitted') or 'no').strip().lower() not in ('no', '')


def _text_of(message):
    """The first plain text part; a mail with only HTML is turned into its words (styles and tags taken out)."""
    import html
    parts = list(message.walk()) if message.is_multipart() else [message]
    for wanted_type in ('text/plain', 'text/html'):
        for part in parts:
            if part.get_content_type() != wanted_type or 'attachment' in str(part.get('Content-Disposition', '')):
                continue
            raw = part.get_payload(decode=True) or b''
            text = raw.decode(part.get_content_charset() or 'utf-8', errors='replace')
            if wanted_type == 'text/html':
                text = re.sub(r'(?is)<(style|script|head|blockquote)[^>]*>.*?</\1>', ' ', text)   # a quoted earlier mail too
                text = re.sub(r'(?i)<br\s*/?>|</(p|div|tr|li|h\d)>', '\n', text)
                text = html.unescape(re.sub(r'<[^>]+>', ' ', text))
            return text
    return ''


def own_text(message):
    """The mail's own words: the first text part, without the quoted earlier mail below it."""
    text = _text_of(message).replace('\r\n', '\n')
    cut = QUOTE.search(text)
    if cut and cut.start() > 20:
        text = text[:cut.start()]
    return _clip(text)


def _sent_folder(conn):
    _, boxes = conn.list()
    for raw in boxes or []:
        line = raw.decode(errors='replace')
        if '\\Sent' in line:
            return line.split(' "/" ')[-1].strip()
    return None


def _fetch_headers(conn, uids):
    fields = 'FROM TO CC SUBJECT DATE RETURN-PATH FEEDBACK-ID LIST-UNSUBSCRIBE LIST-ID PRECEDENCE AUTO-SUBMITTED'
    _, fetched = conn.uid('fetch', b','.join(uids).decode(), f'(UID BODY.PEEK[HEADER.FIELDS ({fields})])')
    rows = []
    for item in fetched or []:
        if not isinstance(item, tuple):
            continue
        uid = re.search(rb'UID (\d+)', item[0])
        rows.append((uid.group(1) if uid else b'', email.message_from_bytes(item[1])))
    return rows


def _search_person(conn, box, name):
    """The named person's mails far back. Gmail's own search reads display names (from:中村) but not a one-character
    name (金); other servers use FROM. When the server finds nothing, the senders of the last mails are read here."""
    since = (datetime.now(timezone.utc) - timedelta(days=DEEP_DAYS)).strftime('%d-%b-%Y')
    if box.startswith('gmail'):
        conn.literal = f'from:({name}) newer_than:{DEEP_DAYS}d'.encode('utf-8')
        _, data = conn.uid('search', 'CHARSET', 'UTF-8', 'X-GM-RAW')
    else:
        conn.literal = name.encode('utf-8')
        _, data = conn.uid('search', 'CHARSET', 'UTF-8', 'SINCE', since, 'FROM')
    found = (data[0] or b'').split() if data else []
    if not found:
        _, data = conn.uid('search', None, 'SINCE', since)
        uids = (data[0] or b'').split()[-DEEP_SCAN:]
        if uids:
            _, fetched = conn.uid('fetch', b','.join(uids).decode(), '(UID BODY.PEEK[HEADER.FIELDS (FROM)])')
            for item in fetched or []:
                if isinstance(item, tuple):
                    uid = re.search(rb'UID (\d+)', item[0])
                    sender = _decode(email.message_from_bytes(item[1]).get('From'))
                    if uid and name in norm(sender):
                        found.append(uid.group(1))
    return found[-40:]


def _connection(box):
    """A mailbox connection kept from the last read (the TLS connect, login and select are about 1.5 s of a read)."""
    from app.services.imap_email_service import connect_mailbox
    with _pool_lock:
        held = _pool.pop(box, None)
    if held and time.monotonic() - held[1] < POOL_S:
        try:
            held[0].noop()
            return held[0]
        except Exception:
            _close(held[0])
    elif held:
        _close(held[0])
    conn = connect_mailbox(box)
    try: conn.sock.settimeout(15)
    except Exception: pass
    return conn


def _close(conn):
    try: conn.logout()
    except Exception: pass


def _keep(box, conn):
    with _pool_lock:
        extra = _pool.get(box)
        _pool[box] = (conn, time.monotonic())
    if extra and extra[0] is not conn:
        _close(extra[0])


def _read_box(box, names, days):
    conn = _connection(box)
    ok = False
    try:
        conn.select('INBOX', readonly=True)
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%d-%b-%Y')
        _, data = conn.uid('search', None, 'SINCE', since)
        uids = (data[0] or b'').split()[-MAIL_HEADERS:]
        found = []
        for uid, head in _fetch_headers(conn, uids) if uids else []:
            found.append(_row(box, uid, head))
        if names and not any(_hits(r, names) for r in found):
            far = [u for u in _search_person(conn, box, max(names, key=len)) if u not in uids]
            if far:
                found += [_row(box, uid, head) for uid, head in _fetch_headers(conn, far)]
        for r in found:
            r['match'] = _hits(r, names) if names else not r['auto']
        picks = sorted((r for r in found if r['match']), key=lambda r: (r['auto'], -r['at'].timestamp()))[:PICK]
        if picks:
            # the header and the first part of the text only (a mail with attachments is megabytes; 11/13 one took 37 s)
            _, fetched = conn.uid('fetch', b','.join(r['uid'] for r in picks).decode(), f'(UID BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.{BODY_BYTES}>)')
            raw, current = {}, None
            for item in fetched or []:
                if not isinstance(item, tuple):
                    continue
                uid = re.search(rb'UID (\d+)', item[0])
                if uid: current = uid.group(1)
                if current is None:
                    continue
                part = raw.setdefault(current, {})
                part['header' if b'HEADER' in item[0].upper() else 'text'] = item[1]
            bodies = {u: email.message_from_bytes(p.get('header', b'') + p.get('text', b'')) for u, p in raw.items()}
            for r in picks:
                r['text'] = own_text(bodies[r['uid']]) if r['uid'] in bodies else ''
        sent = []
        folder = _sent_folder(conn)
        if folder and picks:
            status, _ = conn.select(folder, readonly=True)
            if status == 'OK':
                oldest = min(r['at'] for r in picks).strftime('%d-%b-%Y')
                _, data = conn.uid('search', None, 'SINCE', oldest)
                sent_uids = (data[0] or b'').split()[-200:]
                for _, head in _fetch_headers(conn, sent_uids) if sent_uids else []:
                    try: at = parsedate_to_datetime(head.get('Date'))
                    except Exception: continue
                    to = {parseaddr(a)[1].lower() for a in re.split(r',(?![^<]*>)', head.get('To') or '') + [head.get('Cc') or ''] if a}
                    sent.append((to, at))
        for r in picks:
            r['replied_after'] = any(r['address'] in to and at > r['at'] for to, at in sent)
        ok = True
        return picks
    finally:
        if ok: _keep(box, conn)
        else: _close(conn)


def _hits(row, names):
    return found_in(names, row['from'], row['address'])


def _row(box, uid, head):
    sender = _decode(head.get('From'))
    address = parseaddr(sender)[1].lower()
    try: at = parsedate_to_datetime(head.get('Date')).astimezone(JST)
    except Exception: at = datetime.now(JST)
    headers = {k: head.get(k) or '' for k in ('List-Unsubscribe', 'List-Id', 'Precedence', 'Auto-Submitted', 'Return-Path', 'Feedback-ID')}
    return {'box': box, 'uid': uid, 'from': parseaddr(sender)[0] or address, 'address': address, 'at': at,
            'subject': _decode(head.get('Subject')), 'auto': automated(address, headers), 'match': False}


async def mail(who='', days=MAIL_DAYS):
    """Person mails of the last `days` days in every mailbox, newest first (with who: that person's, also older)."""
    from app.services.imap_email_service import PROVIDERS
    names = words(who)
    key = ('mail', tuple(names), days)
    held = _cache.get(key)
    if held and time.monotonic() - held[1] < CACHE_S:
        return held[0]
    boxes = list(PROVIDERS)
    got = await asyncio.gather(*(asyncio.to_thread(_read_box, b, names, days) for b in boxes), return_exceptions=True)
    rows, failed = [], []
    for box, result in zip(boxes, got):
        if isinstance(result, Exception):
            failed.append(f'{box}（{str(result)[:60]}）')
        else:
            rows += result
    seen, unique = set(), []
    for r in sorted(rows, key=lambda r: (r['auto'], -r['at'].timestamp())):   # people first; one mail sent to two of the owner's addresses
        mark = (r['address'], r['subject'], r['at'].replace(second=0))
        if mark not in seen:
            seen.add(mark); unique.append(r)
    result = {'mails': unique[:10], 'failed': failed, 'read_at': when(time.time()), 'mailboxes': boxes}
    _cache[key] = (result, time.monotonic())
    return result


# ---- LINE -----------------------------------------------------------------------------------------------------------------

async def _d1(user_id, sql, params=None):
    import httpx
    from app.services.credentials_service import get_credentials_service
    found = await get_credentials_service().get_credential(user_id, D1_CREDENTIAL)
    token = str((found or {}).get('password') or '')
    if not token:
        raise RuntimeError('Cloudflare の鍵が保存されていない')
    async with httpx.AsyncClient(timeout=10) as client:
        got = await client.post(D1, headers={'Authorization': 'Bearer ' + token}, json={'sql': sql, 'params': params or []})
    body = got.json()
    if got.status_code != 200 or not body.get('success'):
        raise RuntimeError(f'Cloudflare が {got.status_code} を返した')
    return body['result'][0]['results']


def _what(message):
    kind = message.get('type')
    if kind == 'text':
        return message.get('text') or ''
    return {'image': '（写真）', 'video': '（動画）', 'audio': '（音声）', 'file': '（ファイル）', 'sticker': '（スタンプ）',
            'location': '（位置情報）'}.get(kind, f'（{kind}）')


async def official(user_id, days=MAIL_DAYS):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S')
    rows = await _d1(user_id, "SELECT e.channel_key, e.created_at, e.payload, f.display_name FROM events e LEFT JOIN friends f "
                              "ON f.channel_key=e.channel_key AND f.line_user_id=e.line_user_id WHERE e.type='message' AND e.created_at>=? "
                              "ORDER BY e.id DESC LIMIT 60", [since])
    out = []
    for r in rows:
        payload = json.loads(r.get('payload') or '{}')
        at = datetime.fromisoformat(str(r['created_at']).replace('Z', '+00:00'))
        out.append({'where': CHANNELS.get(r['channel_key'], r['channel_key']), 'sender': r.get('display_name') or '名前不明',
                    'at': at.timestamp(), 'text': _clip(_what(payload.get('message') or {}), 300)})
    if PORNANTI_DB.exists():
        def local():
            with sqlite3.connect(PORNANTI_DB, timeout=3) as c:
                return c.execute("SELECT at, body FROM line_events WHERE type='message' AND at>=? ORDER BY at DESC LIMIT 20",
                                 [time.time() - days * 86400]).fetchall()
        for at, body in await asyncio.to_thread(local):
            payload = json.loads(body or '{}')
            out.append({'where': 'ポルノアンチの公式LINE', 'sender': '名前不明', 'at': at, 'text': _clip(_what(payload.get('message') or {}), 300)})
    return sorted(out, key=lambda r: r['at'], reverse=True)


async def personal(days=MAIL_DAYS):
    from app.services import line_notices
    live = await asyncio.to_thread(line_notices.now)
    rows = {r['id']: {**r, 'unread': True} for r in live}
    for r in await asyncio.to_thread(line_notices.recorded, days):
        rows.setdefault(r['id'], {**r, 'unread': False})
    return sorted(rows.values(), key=lambda r: r['at'], reverse=True)


async def line(user_id, who='', days=MAIL_DAYS):
    names = words(who)
    got = await asyncio.gather(personal(days), official(user_id, days), return_exceptions=True)
    result = {'read_at': when(time.time()), 'failed': []}
    for key, value, label in (('personal', got[0], '個人のLINE（Galaxy の通知）'), ('official', got[1], '公式アカウントの記録')):
        if isinstance(value, Exception):
            result[key] = []
            result['failed'].append(f'{label}（{str(value)[:80]}）')
            continue
        if names:
            value = [r for r in value if found_in(names, r.get('sender'), r.get('talk'), r.get('where'))]
        result[key] = value[:12]
    return result


# ---- for a voice or chat answer ------------------------------------------------------------------------------------------

def mail_digest(found):
    lines = [f"メールの受信箱（{', '.join(found.get('mailboxes') or [])}）を今読んだ（{found.get('read_at')}）。人からのメール:"]
    for r in found.get('mails') or []:
        head = f"■ {when(r['at'])} {r['from']}<{r['address']}>（{r['box']}）件名「{r['subject']}」"
        head += '、本人が後で返信済み' if r.get('replied_after') else ''
        head += '、自動の知らせ' if r.get('auto') else ''
        lines.append(head)
        if r.get('text'):
            lines.append('  ' + ' '.join(r['text'].split()))
    if not found.get('mails'):
        lines.append('  （該当なし）')
    if found.get('failed'):
        lines.append('読めなかった受信箱: ' + '、'.join(found['failed']) + '（届いていないとは言わない）')
    return chr(10).join(lines)


def line_digest(found):
    lines = [f"LINE を今読んだ（{found.get('read_at')}）。個人のLINE（Galaxy の通知。未読と、通知の記録に残っている分。本人の返信・写真の中身は分からない）:"]
    for r in found.get('personal') or []:
        where = f"「{r['talk']}」で" if r.get('group') and r.get('talk') != r.get('sender') else ''
        lines.append(f"  {when(r['at'])} {where}{r['sender']}: {' '.join(str(r['text']).split())[:300]}" + ('（未読）' if r.get('unread') else ''))
    if not found.get('personal'):
        lines.append('  （該当なし）')
    lines.append('公式アカウントに届いた分（本人が管理画面から返したかはここでは分からない）:')
    for r in found.get('official') or []:
        lines.append(f"  {when(r['at'])} {r['where']}に {r['sender']}: {' '.join(str(r['text']).split())}")
    if not found.get('official'):
        lines.append('  （該当なし）')
    if found.get('failed'):
        lines.append('読めなかったもの: ' + '、'.join(found['failed']) + '（届いていないとは言わない）')
    return chr(10).join(lines)


async def everything(user_id, who='', limit=9000):
    """Chatwork, mail and LINE read side by side, as text for the model that answers (about 3 s, the mail is the slowest)."""
    from app.services import chatwork_read
    began = time.monotonic()
    cw, ml, ln = await asyncio.gather(chatwork_read.read(user_id, who=who), mail(who), line(user_id, who), return_exceptions=True)
    parts = []
    parts.append(f'Chatwork は読めなかった（{cw}）。' if isinstance(cw, Exception) else chatwork_read.spoken_digest(cw, limit=limit // 3))
    parts.append(f'メールは読めなかった（{ml}）。' if isinstance(ml, Exception) else mail_digest(ml)[:limit // 3])
    parts.append(f'LINE は読めなかった（{ln}）。' if isinstance(ln, Exception) else line_digest(ln)[:limit // 3])
    return (chr(10) * 2).join(parts), round((time.monotonic() - began) * 1000)
