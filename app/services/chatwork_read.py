"""Reading the owner's Chatwork through its API (read only), for calls and chat Dan (2026-11-13, the owner).

Why: on the 11/12 22:44 call 「中村さんから連絡ありましたか」 took about 6 minutes: Chatwork's notice mail says only that
something unread is in a room, so chat Dan opened Chatwork in the browser and read it there (5 min 40 s); the owner hung up
after 2 min 27 s. The owner issued an API token (credentials service, 'chatwork_api') and said to take in APIs that make
Dan fast and accurate. One read of the rooms and their latest messages takes about a second.

Only GET requests are made here. Reading messages with force=1 does not change what is unread in Chatwork. Sending stays
with the outbound message card (compose_message) after the owner's approval; nothing here sends or marks as read.
"""
import asyncio
import re
import time
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

API = 'https://api.chatwork.com/v2'
CREDENTIAL = 'chatwork_api'
TOKEN_TTL_S = 600
CACHE_S = 20            # one call asks again within seconds (「中身は？」 right after 「来てる？」)
TEXT = 500              # characters of one message
JST = ZoneInfo('Asia/Tokyo')
HONORIFICS = re.compile(r'(さん|様|さま|くん|君|ちゃん|先生|氏)$')

_tokens = {}            # user id -> (token, read at); process memory only
_cache = {}             # (user id, path) -> (value, read at)


class Unavailable(Exception):
    """No token saved, or Chatwork refused or did not answer."""


async def token(user_id):
    held = _tokens.get(user_id)
    if held and time.monotonic() - held[1] < TOKEN_TTL_S:
        return held[0]
    from app.services.credentials_service import get_credentials_service
    found = await get_credentials_service().get_credential(user_id, CREDENTIAL)
    value = str((found or {}).get('password') or '').strip()
    if not value:
        raise Unavailable('Chatwork の API トークンが保存されていない')
    _tokens[user_id] = (value, time.monotonic())
    return value


async def _get(user_id, path, params=None):
    key = (user_id, path, tuple(sorted((params or {}).items())))
    held = _cache.get(key)
    if held and time.monotonic() - held[1] < CACHE_S:
        return held[0]
    import httpx
    headers = {'X-ChatWorkToken': await token(user_id)}
    try:
        async with httpx.AsyncClient(base_url=API, headers=headers, timeout=10) as client:
            got = await client.get(path, params=params)
    except httpx.HTTPError as exc:
        raise Unavailable(f'Chatwork に届かなかった（{type(exc).__name__}）')
    if got.status_code == 204:
        value = []
    elif got.status_code == 401:
        _tokens.pop(user_id, None)
        raise Unavailable('Chatwork がトークンを受け付けなかった（無効か取り消された）')
    elif got.status_code == 429:
        raise Unavailable('Chatwork の読み出しの上限に当たった（5分ほどで戻る）')
    elif got.status_code >= 400:
        raise Unavailable(f'Chatwork が {got.status_code} を返した')
    else:
        value = got.json()
    _cache[key] = (value, time.monotonic())
    if len(_cache) > 256:
        _cache.pop(next(iter(_cache)))
    return value


def when(stamp):
    moment = datetime.fromtimestamp(int(stamp or 0), JST)
    return f'{moment.month}月{moment.day}日 {moment.hour}:{moment.minute:02d}'


def plain(body):
    """The message as a person reads it: Chatwork's tags turned into words."""
    text = str(body or '')
    text = re.sub(r'\[To:\d+\]\s*', '@', text)
    text = re.sub(r'\[toall\]', '@全員 ', text)
    text = re.sub(r'\[rp aid=\d+[^\]]*\]\s*', '（返信）', text)
    text = re.sub(r'\[qt\]\[qtmeta[^\]]*\]', '（引用: ', text).replace('[/qt]', '）')
    text = re.sub(r'\[download:\d+\](.*?)\[/download\]', r'（ファイル: \1）', text, flags=re.S)
    text = re.sub(r'\[preview[^\]]*\]', '', text)
    text = re.sub(r'\[title\]\[dtext:file_uploaded\]\[/title\]', '', text)
    text = re.sub(r'\[dtext:([a-z_]+)\]', '', text)
    text = re.sub(r'\[piconname:\d+\]', '', text)
    text = re.sub(r'\[/?(info|title|code|hr|task[^\]]*)\]', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text if len(text) <= TEXT else text[:TEXT] + f'…（全{len(text)}字）'


def norm(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(text or ''))).lower()


def wanted(who):
    """The name the owner said, without 「さん」 and the like (「中村さん」 -> 「中村」)."""
    return HONORIFICS.sub('', norm(who))


def words(who):
    """The words of what the owner named, each without its honorific: a model asks 「イツキ 高橋さん」 (11/13)."""
    return [w for w in (HONORIFICS.sub('', norm(part)) for part in re.split(r'[\s　、,・]+', str(who or ''))) if w]


def found_in(names, *texts):
    """Every word named is somewhere in these texts (the sender, the room, the account)."""
    hay = ''.join(norm(t) for t in texts)
    return bool(names) and all(n in hay for n in names)


async def read(user_id, who='', room_id=None, messages=5, days=7):
    """What is in Chatwork now.

    who: a person or room the owner named. Rooms whose name has it, and rooms where that person wrote recently, come back
    with their latest messages. Without who: the rooms that moved in the last `days` days, the direct ones and those with
    a mention first. room_id: one room, its latest messages (up to 100).
    """
    me = await _get(user_id, '/me')
    my_id = me.get('account_id')
    rooms = await _get(user_id, '/rooms')
    rooms = sorted(rooms, key=lambda r: r.get('last_update_time') or 0, reverse=True)
    if room_id:
        rooms = [r for r in rooms if str(r.get('room_id')) == str(room_id)]
        if not rooms:
            return {'rooms': [], 'note': f'Chatwork に room_id {room_id} の部屋は無い。'}
        picked, per_room = rooms, max(1, min(int(messages or 20), 100))
    else:
        since = time.time() - days * 86400
        recent = [r for r in rooms if (r.get('last_update_time') or 0) >= since] or rooms[:3]
        picked, per_room = recent[:10], max(1, min(int(messages or 5), 20))
    names = words(who)

    async def latest(room):
        got = await _get(user_id, f"/rooms/{room['room_id']}/messages", {'force': 1})
        return room, got or []

    read_rooms = await asyncio.gather(*(latest(r) for r in picked))
    out = []
    for room, items in read_rooms:
        if names and not room_id:
            in_name = found_in(names, room.get('name'))
            theirs = [m for m in items if found_in(names, (m.get('account') or {}).get('name'), room.get('name'))]
            if not in_name and not theirs:
                continue
            if not in_name and room.get('type') == 'group':   # a big group room: only the last few things that person wrote
                items = theirs[-2:]
        rows = []
        for m in items[-per_room:]:
            account = m.get('account') or {}
            rows.append({'from': '本人' if account.get('account_id') == my_id else account.get('name'),
                         'at': when(m.get('send_time')), 'text': plain(m.get('body'))})
        last_other = next((m for m in reversed(items) if (m.get('account') or {}).get('account_id') != my_id), None)
        out.append({'room': room.get('name'), 'room_id': room.get('room_id'), 'kind': {'direct': '1対1', 'group': 'グループ', 'my': '自分用'}.get(room.get('type'), room.get('type')),
                    'unread': room.get('unread_num', 0), 'mentions': room.get('mention_num', 0), 'updated': when(room.get('last_update_time')),
                    'last_from_others': when(last_other.get('send_time')) if last_other else None,
                    'replied_after': bool(last_other) and bool(items) and (items[-1].get('account') or {}).get('account_id') == my_id,
                    'messages': rows})
    if not room_id:   # direct rooms and those with a mention first: a course's busy group chat is not what 「連絡来てる？」 means
        out.sort(key=lambda r: (r['kind'] != '1対1', -(r['mentions'] or 0)))
    result = {'rooms': out, 'read_at': when(time.time()), 'account': me.get('name'),
              'note': ('「本人」は持ち主自身の発言。replied_after=true は相手の最後の発言の後に本人が返している。'
                       'unread は Chatwork の画面の未読数（ここで読んでも変わらない）。')}
    if names and not out:
        result['note'] = (f'最近{days}日に動いた部屋に「{who}」の名前の部屋も発言も無かった。部屋の一覧: '
                          + '、'.join(f"{r.get('name')}（{when(r.get('last_update_time'))}）" for r in rooms[:12]))
    return result


def spoken_digest(found, limit=3000):
    """The read as text for a model that answers by voice: rooms newest first, each message on one line."""
    lines = [f"Chatwork を今読んだ（{found.get('read_at')}）。"]
    for room in found.get('rooms') or []:
        head = f"■ {room['room']}（{room['kind']}、最後の動き {room['updated']}"
        head += f"、未読{room['unread']}" if room.get('unread') else ''
        head += f"、本人あての未読{room['mentions']}" if room.get('mentions') else ''
        head += '、本人が最後に返信済み' if room.get('replied_after') else ''
        lines.append(head + '）')
        lines += [f"  {m['at']} {m['from']}: {' '.join(m['text'].split())}" for m in room['messages']]
    if found.get('note') and not found.get('rooms'):
        lines.append(found['note'])
    text = chr(10).join(lines)
    return text if len(text) <= limit else text[:limit] + '…'
