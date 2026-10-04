"""The inbox: what reaches a user from outside comes in at one place, Dan judges each item, and the outcome is said in chat.

Design (owner, 2026-10-01; https://claude.ai/artifact/CDjeQo1x1uSGNqLJGHFYxd): per user, the channels the user connected
feed one queue; a sieve of rules drops what is plainly not for a person (lists, automatic mail, the user's own mail); Dan
judges the rest with the user's memory, what Dan is waiting for (mail watches) and the recent rooms: ignore / log / tell /
act. A told item is Dan's line in the room it belongs to (else the user's home room) with a push; an acted item wakes Dan
in that room to handle it (reply drafts come as send cards; nothing is sent without approval). No notification bell.

Stage 1 is mail. Each user's mailboxes are that user's own (any provider over IMAP); nothing about one user reaches
another. Kept per user, encrypted: ~/.dan/inbox/<user>.json = {mailboxes: [{address, host, port, password}], home_room,
uids: {address: last uid}, pending: [detected ids not judged yet]}.

Switch: DAN_INBOX=0 (the old email poller routing runs instead).
"""
import asyncio
import email
import imaplib
import json
import logging
import os
import re
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)
ROOT = Path.home()/'.dan'/'inbox'
FETCH_MAX = 30
HOSTS = {'gmail.com': 'imap.gmail.com', 'googlemail.com': 'imap.gmail.com', 'icloud.com': 'imap.mail.me.com',
         'me.com': 'imap.mail.me.com', 'mac.com': 'imap.mail.me.com', 'outlook.com': 'outlook.office365.com',
         'hotmail.com': 'outlook.office365.com', 'live.com': 'outlook.office365.com', 'yahoo.co.jp': 'imap.mail.yahoo.co.jp',
         'yahoo.com': 'imap.mail.yahoo.com'}
_lock = threading.Lock()


def enabled():
    return os.environ.get('DAN_INBOX', '1') != '0'


# ---- per-user settings ------------------------------------------------------------------------------------

def _file(user_id):
    return ROOT/f'{user_id}.json'


def settings(user_id):
    path = _file(user_id)
    if not path.exists():
        return {}
    from app.services.encryption import decrypt_data
    try:
        return json.loads(decrypt_data(path.read_text(encoding='utf-8').strip()))
    except Exception:
        logger.exception('inbox settings unreadable for %s', user_id)
        return {}


def save(user_id, data):
    from app.services.encryption import encrypt_data
    ROOT.mkdir(parents=True, exist_ok=True)
    temp = _file(user_id).with_suffix('.tmp')
    temp.write_text(encrypt_data(json.dumps(data, ensure_ascii=False)), encoding='utf-8')
    os.replace(temp, _file(user_id))


def users():
    return [p.stem for p in ROOT.glob('*.json')] if ROOT.exists() else []


def connect_mailbox(user_id, address, password, host='', port=993):
    """Add (or replace) one of the user's mailboxes. The login is tried first; nothing is kept if it fails."""
    address = address.strip().lower()
    host = host or HOSTS.get(address.split('@')[-1], 'imap.' + address.split('@')[-1])
    box = {'address': address, 'host': host, 'port': int(port), 'password': password}
    _login(box).logout()
    with _lock:
        data = settings(user_id)
        data['mailboxes'] = [b for b in data.get('mailboxes', []) if b['address'] != address] + [box]
        save(user_id, data)
    return {'address': address, 'host': host}


def set_home_room(user_id, room_id):
    with _lock:
        data = settings(user_id); data['home_room'] = room_id; save(user_id, data)


async def home_room(user_id):
    room = settings(user_id).get('home_room')
    if room:
        return room
    from app.services.chat_service import ChatService
    return (await ChatService().get_or_create_dan_room(user_id))['id']


# ---- fetching -------------------------------------------------------------------------------------------

def _login(box):
    M = imaplib.IMAP4_SSL(box['host'], box.get('port', 993))
    try:
        try: M.login(box['address'], box['password'])
        except imaplib.IMAP4.error: M.login(box['address'], box['password'].replace(' ', '').replace('-', ''))
    except imaplib.IMAP4.error as exc:
        try: M.logout()
        except Exception: pass
        raise RuntimeError(f'{box["address"]}: login failed: {exc}') from exc
    return M


def _fetch(box, last_uid):
    """New mails above last_uid (PEEK: they stay unread). The first time only the newest UID is noted: an inbox connected
    today starts from today, its history is not news. Returns (mails, new last uid)."""
    from app.services.imap_email_service import _decode_mime_header, _extract_body, _extract_and_save_attachments
    M = _login(box)
    try:
        M.select('INBOX', readonly=True)
        typ, data = M.uid('SEARCH', None, f'UID {last_uid + 1}:*' if last_uid else 'ALL')
        uids = [int(u) for u in (data[0].split() if typ == 'OK' and data and data[0] else [])]
        uids = [u for u in uids if u > last_uid]
        if not last_uid:
            return [], max(uids or [0])
        mails = []
        for uid in uids[:FETCH_MAX]:
            typ, msg_data = M.uid('FETCH', str(uid).encode(), '(BODY.PEEK[])')
            if typ != 'OK' or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            message_id = (msg.get('Message-ID') or f'{box["address"]}-uid-{uid}').strip()
            mails.append({
                'uid': uid, 'message_id': message_id, 'subject': _decode_mime_header(msg.get('Subject')),
                'from': _decode_mime_header(msg.get('From')), 'to': _decode_mime_header(msg.get('To')),
                'date': msg.get('Date') or '', 'body': _extract_body(msg),
                'attachments': _extract_and_save_attachments(msg, re.sub(r'[<>/]', '', message_id)[:80]),
                'headers': {k: (msg.get(k) or '').strip()[:300] for k in ('List-Unsubscribe', 'List-Id', 'Precedence', 'Auto-Submitted',
                                                                           'In-Reply-To', 'References', 'X-Dan-Ref')}})
        return mails, max([last_uid] + uids[:FETCH_MAX])
    finally:
        try: M.logout()
        except Exception: pass


async def _store(user_id, box, mail):
    """Into the queue (detected_messages, one row per Message-ID across all of the user's mailboxes). Returns the row when
    it is new, None when the same mail was already queued (it reached two of the user's addresses)."""
    from app.services.message_detection import get_detection_service
    from app.models.detection_schemas import MessageSource
    row = await get_detection_service().detect_message(
        user_id=user_id, source=MessageSource.GMAIL, content=mail['body'], source_id=mail['message_id'], subject=mail['subject'],
        sender_info={'from': mail['from'], 'to': mail['to'], 'date': mail['date'], 'provider': box['address']},
        metadata={'attachments': mail['attachments'], 'uid': mail['uid'], 'provider': box['address'], 'message_id': mail['message_id'],
                  'in_reply_to': mail['headers'].get('In-Reply-To') or None, 'references': mail['headers'].get('References') or None,
                  'routing_key': mail['headers'].get('X-Dan-Ref') or None, 'headers': mail['headers'], 'inbox': 'pending'})
    return row if row and row.get('content') is not None else None


# ---- judging --------------------------------------------------------------------------------------------

def _address(text):
    found = re.findall(r'[\w.+-]+@[\w.-]+', text or '')
    return found[0].lower() if found else ''


def sieve(item, own):
    """Rules before any model: '' to go on, or the reason it stops here. Only what is certainly not for the user stops
    here; a newsletter header is not that (an important bank notice or account notice comes the same way), so lists,
    bulk and automatic mail go to the judge, which follows the user's wishes (user_prefs) about them (owner, 2026-10-02)."""
    meta = item.get('metadata') or {}
    headers = meta.get('headers') or {}
    sender = _address((item.get('sender_info') or {}).get('from'))
    if sender and sender in own:
        return 'own'                       # the user's own mail, seen from another of their addresses
    if re.match(r'(mailer-daemon|postmaster)@', sender or ''):
        return 'bounce'
    if CODE.search(item.get('subject') or ''):
        return 'code'   # a one-time code: Dan reads it itself when it is the one logging in; told, it is already used up
    return ''


CODE = re.compile(r'(verification|security|login|sign.?in|one.?time)\s*code|OTP|passcode|認証コード|確認コード|ワンタイム|セキュリティコード|'
                  r'^\s*\d{4,8}\s*(is your|は)', re.I)
REPEAT_HOURS = 24


def repeat_key(item):
    """The same notice again: same sender, same subject once its numbers, hashes and parentheses are taken out."""
    subject = re.sub(r'\(.*?\)|（.*?）|#?[0-9a-f]{7,}|\d+', '', (item.get('subject') or '').lower())
    return _address((item.get('sender_info') or {}).get('from')) + '|' + re.sub(r'\s+', ' ', subject).strip()


def repeated(told, key, now):
    """Told within the last REPEAT_HOURS: say it once, not each time it comes again."""
    return now - told.get(key, 0) < REPEAT_HOURS*3600


def _mail_watches(user_id):
    """What Dan is waiting for by mail: the user's active mail watches."""
    try:
        from app.services.followups import TABLE, decode_watch_row
        from app.services.supabase_client import get_supabase_client
        rows = (get_supabase_client().client.table(TABLE).select('*').eq('user_id', user_id).eq('status', 'pending').execute().data or [])
    except Exception:
        return []
    out = []
    for row in rows:
        d = decode_watch_row(row)
        if d.get('kind') == 'mail':
            out.append({'id': row['id'], 'room_id': row['room_id'], 'from': (d.get('spec') or {}).get('from', ''),
                        'subject': (d.get('spec') or {}).get('subject_contains', ''), 'note': d.get('plain_note') or ''})
    return out


def _recent_rooms(user_id, limit=300):
    """All of the user's rooms, newest first (a project quiet for a month is still where its mail belongs; the old router
    saw only the newest 15)."""
    try:
        from app.services.supabase_client import get_supabase_client
        sb = get_supabase_client().client
        rows = (sb.table('projects').select('room_id,title,updated_at').eq('user_id', user_id)
                .order('updated_at', desc=True).limit(limit).execute().data or [])
        return [{'room_id': r['room_id'], 'title': r.get('title') or ''} for r in rows if r.get('room_id')]
    except Exception:
        return []


def _rooms_that_know(sender, rooms):
    """Rooms whose conversation has mentioned this sender's address: the likeliest homes of their mail."""
    if not sender or not rooms:
        return []
    try:
        from app.services.supabase_client import get_supabase_client
        sb = get_supabase_client().client
        ids = [r['room_id'] for r in rooms]
        found = []
        for start in range(0, len(ids), 100):
            rows = (sb.table('chat_messages').select('room_id').in_('room_id', ids[start:start+100])
                    .ilike('content', f'%{sender}%').limit(50).execute().data or [])
            found += [r['room_id'] for r in rows if r['room_id'] not in found]
        return found[:5]
    except Exception:
        return []


def watch_hit(item, watches):
    """A mail watch whose condition (sender, and subject when given) the mail meets. The condition is often only the sender,
    so a hit is a strong lead, not the answer: judge() looks at the mail with the watch in hand."""
    sender = ((item.get('sender_info') or {}).get('from') or '').lower()
    subject = (item.get('subject') or '').lower()
    for watch in watches:
        want = (watch.get('from') or '').strip().lower()
        if want and want in sender and (not watch.get('subject') or watch['subject'].lower() in subject):
            return watch
    return None


JUDGE = """あなたはダン（本人の秘書AI）。本人あてに外から届いたもの（メール、SNS の DM や通知、サイトの問い合わせ、外部窓口のチャットなど。channel に書いてある）を1件ずつ見て、無視するか、対応するかを決める。
届いたものは全部残るので（後で探せる）、本人に関係ないもの（広告・お知らせ・本人に用のない自動通知）は無視でよい。
本人やダンが自分でした操作の確認（予約完了・予約確認・注文受付・登録完了・本人のログインの通知など）も、問題が書かれていなければ無視。
対応するなら、その大きさも自分で決める:
- tell: 一言で足りる（本人が知っておけばよい。人からの連絡・期限・お金・予定・待っていた返事など）。
- act: 作業が要る（返事を書く・調べる・準備する。本人の記憶にその使い道があるもの、例: 経費の領収書）。送信や支払いは本人の承認後なので準備と提案まで。
「本人の希望」が渡されたら、何よりそれに従う（いらないと言われた種類は無視、知らせてと言われた種類は知らせる）。
待っている目印（ダンが待っているもの）に当たるメールは、言い回しが違っても、その目印の部屋で対応する。
部屋は、話の続きなら部屋の一覧から選ぶ（「差出人が出てきた部屋」があればまずそこ）。どれでもなければ空。
JSONだけを返す: {"decision": "ignore|tell|act", "room_id": "", "watch_id": "", "line": "本人への一言（対応する時。日本語で短く、差出人と要点）", "why": "短く"}"""


def _env():
    """The model's keys, read from .env as the job worker does (the core's environment does not carry them)."""
    from dotenv import dotenv_values
    fresh = dotenv_values(Path(__file__).resolve().parents[2]/'.env')
    for key in ('DAN_INBOX_MODEL', 'DAN_API_JOB_MODEL', 'DEEPSEEK_API_KEY', 'DAN_CHAT_BASE_URL', 'DAN_CHAT_API_KEY', 'ANTHROPIC_API_KEY'):
        if fresh.get(key) and not os.environ.get(key): os.environ[key] = fresh[key]


async def judge(user_id, item, watches, rooms, hint=None, known=(), matched=None, belongs=None):
    """Dan's decision for one item."""
    from app.services import api_job_providers
    mail = item.get('sender_info') or {}
    body = (item.get('content') or '').strip()[:3000]
    facts = {'channel': item.get('source') or 'gmail', 'from': mail.get('from'), 'to': mail.get('to'), 'subject': item.get('subject'), 'date': mail.get('date'),
             'attachments': [a.get('filename') for a in ((item.get('metadata') or {}).get('attachments') or []) if isinstance(a, dict)][:5]}
    from app.services import user_prefs
    wishes = [r['text'] for r in user_prefs.items(user_id, ('連絡', '全般'))]
    context = ((f'本人の希望: {json.dumps(wishes, ensure_ascii=False)}\n' if wishes else '')
               + f'待っている目印: {json.dumps(watches, ensure_ascii=False)}\n部屋の一覧（新しい順）: {json.dumps(rooms, ensure_ascii=False)}\n'
               + (f'差出人が出てきた部屋: {json.dumps(list(known))}\n' if known else '')
               + (f'送った連絡への返事として照合できた部屋: {hint}\n' if hint else '')
               + (f'このメールが条件（差出人など）に合った目印: {json.dumps(matched, ensure_ascii=False)}\n'
                  '条件は差出人だけのことが多い。中身がその目印で待っているもの（返事・結果・届いた物）なら、その watch_id で対応する。'
                  'そうでなければ（同じ相手からの別の連絡、ダン自身の操作の確認など）目印とは関係なく、ほかのメールと同じに判断する。\n'
                  if matched else '')
               + (f'これが届いた部屋（外部窓口など）: {belongs}\n' if belongs else '')
               + f'届いたもの: {json.dumps(facts, ensure_ascii=False)}\n本文:\n{body}')
    _env()
    provider = api_job_providers.make(os.environ.get('DAN_INBOX_MODEL') or os.environ.get('DAN_API_JOB_MODEL', 'deepseek-flash'))
    provider.start(JUDGE, [], [context])
    step = await provider.step()
    text = step['text']
    try:
        decision = json.loads(re.search(r'\{.*\}', text, re.S).group(0))
    except Exception:
        decision = {'decision': 'tell', 'line': f'メールが届きました: {facts["from"]}「{facts["subject"]}」', 'why': 'judge_unreadable'}
    if decision.get('decision') == 'log':
        decision['decision'] = 'ignore'
    if decision.get('decision') not in ('ignore', 'tell', 'act'):
        decision['decision'] = 'tell'
    return decision


_ACT_PROMPT = ('[受け口 / 届いた連絡の自動処理]\nこれは本人の発言ではない。本人あてに届いた連絡（{channel}）を、ダンが「動くべき」と判断した。\n'
               '判断の理由: {why}\n{watch}\n--- 届いた連絡 ---\n差出人: {sender}\n件名: {subject}\n受信日時: {date}\n本文:\n{body}\n--- ここまで ---\n\n'
               'この部屋の経緯を踏まえて、要点を本人に短く報告し、次の行動を具体的に提案する。返事が要るなら返信文を compose_message の送信案カードで出す'
               '（本文をチャットに書かない）。本人の承認なしに送信・支払い・外部への働きかけをしない。')


async def deliver(user_id, item, decision, watches):
    """The outcome, said in chat (and pushed). Returns the room it went to."""
    from app.services.chat_service import ChatService
    known = {r['room_id'] for r in _recent_rooms(user_id)}
    watch = next((w for w in watches if w['id'] == decision.get('watch_id')), None)
    room = (watch or {}).get('room_id') or (decision.get('room_id') if decision.get('room_id') in known else '') or await home_room(user_id)
    line = (decision.get('line') or '').strip()
    mail = item.get('sender_info') or {}
    if decision['decision'] == 'act':
        from app.services.inbound_wakeup import schedule_room_wakeup
        prompt = _ACT_PROMPT.format(channel=item.get('source') or 'gmail', why=decision.get('why') or '', watch=(f'待っていた目印: 「{watch["note"]}」\n' if watch else ''),
                                    sender=mail.get('from') or '', subject=item.get('subject') or '', date=mail.get('date') or '',
                                    body=(item.get('content') or '')[:2500])
        wake_item = {**item, '_inbox_prompt': prompt}
        if not schedule_room_wakeup(wake_item, room, reason='inbox'):
            await ChatService().send_message(room, user_id, line or prompt[:400], sender_type='ai')
    elif decision['decision'] == 'tell' and line:
        await ChatService().send_message(room, user_id, line, sender_type='ai')
    if decision['decision'] in ('tell', 'act') and line:
        try:
            from app.services.push_service import get_push_service
            await get_push_service().notify_room(room_id=f'user:{user_id}', exclude_type='ai', title='Dan', body=line[:120], url='/chat')
        except Exception:
            pass
    return room


async def say(user_id, room_id, text, push=True):
    """Dan's line in a room (the user's home room when none), pushed. Everything the bell used to hold is said here."""
    from app.services.chat_service import ChatService
    try:
        room = room_id or await home_room(user_id)
        message = await ChatService().send_message(room, user_id, text, sender_type='ai')
    except Exception:
        logger.exception('inbox: could not say in %s', room_id)   # never breaks the caller; the record stays where it was
        return None
    if push:
        try:
            from app.services.push_service import get_push_service
            await get_push_service().notify_room(room_id=f'user:{user_id}', exclude_type='ai', title='Dan', body=text[:120], url='/chat')
        except Exception:
            pass
    return message


def say_soon(user_id, room_id, text):
    """say() from code that is not async: on the running loop when there is one, else here and now."""
    try:
        asyncio.get_running_loop().create_task(say(user_id, room_id, text))
    except RuntimeError:
        try: asyncio.run(say(user_id, room_id, text))
        except Exception: logger.exception('inbox: could not say in %s', room_id)


def _mark(item_id, result):
    if not item_id:
        return
    try:
        from app.services.supabase_client import get_supabase_client
        sb = get_supabase_client().client
        row = sb.table('detected_messages').select('metadata').eq('id', item_id).limit(1).execute().data
        meta = (row[0].get('metadata') if row else None) or {}
        meta['inbox'] = result
        sb.table('detected_messages').update({'metadata': meta}).eq('id', item_id).execute()
    except Exception:
        logger.warning('inbox: could not mark %s', item_id)


async def handle(user_id, item, own):
    """One item through the sieve, Dan's judgement and the outlet."""
    reason = sieve(item, own)
    if reason:
        _mark(item['id'], {'decision': 'ignore', 'by': 'rule', 'why': reason, 'at': time.time()})
        return 'ignore'
    watches = await asyncio.to_thread(_mail_watches, user_id)
    mail = (item.get('source') or 'gmail') == 'gmail'
    hit = watch_hit(item, watches) if mail else None   # mail watches name a sender address
    belongs = (item.get('metadata') or {}).get('room_hint')   # where a non-mail item plainly belongs (a collab window's room)
    rooms = await asyncio.to_thread(_recent_rooms, user_id)
    hint = None
    try:   # a reply to something Dan sent: the ledger knows the room
        from app.services.external_message_routing import get_external_message_routing_service
        from app.services.external_message_routing import STRONG_REASONS
        match = get_external_message_routing_service().find_route(item)
        if match and match.reason in STRONG_REASONS:
            hint = (match.route or {}).get('origin_room_id')
    except Exception:
        pass
    known = await asyncio.to_thread(_rooms_that_know, _address((item.get('sender_info') or {}).get('from')), rooms)
    decision = await judge(user_id, item, watches, rooms, hint, known, matched=hit, belongs=belongs)
    awaited = bool(hit) and decision['decision'] in ('tell', 'act') and decision.get('watch_id') in (None, '', hit['id'])
    if awaited:   # the awaited thing: handled in the watch's room
        decision['watch_id'], decision['room_id'] = hit['id'], hit['room_id']
    if hint and decision['decision'] == 'ignore':
        decision['decision'] = 'tell'   # a reply to Dan's own message is never silently dropped
    if mail and not hint and not awaited and decision['decision'] in ('tell', 'act'):   # repeats are a mail habit (the same notice again)
        key, now = repeat_key(item), time.time()
        with _lock:
            data = settings(user_id); told = data.get('told') or {}
            if repeated(told, key, now):
                decision = {**decision, 'decision': 'ignore', 'why': 'repeat: ' + (decision.get('why') or '')}
            else:
                told[key] = now
                data['told'] = {k: t for k, t in told.items() if now - t < REPEAT_HOURS*3600*2}; save(user_id, data)
    if (hint or belongs) and not decision.get('room_id'):
        decision['room_id'] = hint or belongs
    room = None
    if decision['decision'] in ('tell', 'act'):
        room = await deliver(user_id, item, decision, watches)
    _mark(item['id'], {**decision, 'room': room, 'by': 'dan', 'at': time.time()})
    return decision['decision']


async def pending_sms(user_id):
    """SMS the phone forwarded while Dan was elsewhere: the always-up landing (Vercel) keeps them as pending rows; judged
    here like any other item. Marked 'judging' first so the next round does not take the same one."""
    from app.services.supabase_client import get_supabase_client
    sb = get_supabase_client().client
    rows = await asyncio.to_thread(lambda: sb.table('detected_messages').select('*').eq('user_id', user_id).eq('source', 'sms')
                                   .eq('status', 'pending').eq('metadata->>inbox', 'pending').limit(20).execute().data or [])
    for row in rows:
        _mark(row['id'], 'judging')
        try:
            await judge_row(user_id, row)
        except Exception:
            logger.exception('inbox: judging sms %s failed', row['id'])
            _mark(row['id'], 'pending')
    return len(rows)


async def cycle(user_id):
    """Fetch every mailbox of the user, queue what is new, judge it."""
    try:
        await pending_sms(user_id)
    except Exception:
        logger.exception('inbox: forwarded SMS not read')
    data = await asyncio.to_thread(settings, user_id)
    boxes = data.get('mailboxes') or []
    own = {b['address'] for b in boxes}
    uids = dict(data.get('uids') or {})
    pending = list(data.get('pending') or [])
    for box in boxes:
        try:
            mails, last = await asyncio.to_thread(_fetch, box, int(uids.get(box['address']) or 0))
        except Exception as exc:
            logger.warning('inbox %s: %s', box['address'], exc)
            continue
        for mail in mails:
            try:
                row = await _store(user_id, box, mail)
                if row: pending.append(row['id'])
            except Exception:
                logger.exception('inbox: store failed %s', box['address'])
        uids[box['address']] = last
    with _lock:
        fresh = settings(user_id); fresh['uids'] = uids; fresh['pending'] = pending; save(user_id, fresh)
    if not pending:
        return 0
    from app.services.supabase_client import get_supabase_client
    sb = get_supabase_client().client
    left = []
    for item_id in pending:
        try:
            rows = sb.table('detected_messages').select('*').eq('id', item_id).limit(1).execute().data
            if rows: await handle(user_id, rows[0], own)
        except Exception:
            logger.exception('inbox: judging %s failed; kept for the next round', item_id)
            left.append(item_id)
    with _lock:
        fresh = settings(user_id); fresh['pending'] = left; save(user_id, fresh)
    return len(pending) - len(left)


async def cycle_all():
    for user_id in users():
        try:
            await cycle(user_id)
        except Exception:
            logger.exception('inbox cycle failed for %s', user_id)
    try:   # the SNS pages the users asked Dan to watch (feeds.py), those that are due
        from app.services import feeds
        asyncio.get_running_loop().create_task(feeds.cycle_all())
    except Exception:
        logger.exception('feeds cycle not started')


# ---- stage 2: what reaches the user by other ways than mail ----------------------------------------------------------

async def receive(user_id, source, sender, body, subject='', source_id='', room_id=None, metadata=None):
    """Something that reached the user from outside by another way than mail (an Instagram DM, a guest in a collab
    window, a site inquiry, a watched SNS page): kept in the same queue and judged the same way. room_id: the room it
    plainly belongs to (a collab window's origin room). Returns the decision, or None when it was already received."""
    from app.services.supabase_client import get_supabase_client
    sb = get_supabase_client().client
    if source_id:
        found = await asyncio.to_thread(lambda: sb.table('detected_messages').select('id').eq('user_id', user_id)
                                        .eq('source_id', source_id).limit(1).execute().data)
        if found:
            return None
    row = {'user_id': user_id, 'source': source, 'source_id': source_id or None, 'content': body or '', 'subject': subject or '',
           'sender_info': {'from': sender}, 'metadata': {**(metadata or {}), 'room_hint': room_id, 'inbox': 'pending'}, 'status': 'pending'}
    stored = await asyncio.to_thread(lambda: sb.table('detected_messages').insert(row).execute().data)
    return await handle(user_id, stored[0] if stored else {**row, 'id': None}, set())


async def judge_row(user_id, row):
    """A non-mail item already in the queue (the Instagram poller stores its own rows)."""
    return await handle(user_id, row, set())


def soon(coro):
    """Run one of the above from code that is not async: on the running loop when there is one, else here and now."""
    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        try: asyncio.run(coro)
        except Exception: logger.exception('inbox: could not receive')
