"""Dan calls the owner the moment the work cannot go on without them (owner, 2026-10-27).

本人「法人口座からアプリで振り込みをするとき、僕がリアルタイムで張り付いて6桁の承認番号を入れないと振り込みが失敗して
しまうことがよくありますよね。そういう時は、僕が画面から目を離していても、チャット形式だけじゃなく音を鳴らして…
リアルタイムで通知を飛ばしてほしい。ダンが受動的に待つだけじゃなく、能動的に働きかけられるようにしたい」

Until now such a wait was one line in the chat: a phone notification with the ordinary sound, once, and the code ran out
while the owner looked elsewhere. A summons is the other kind of message:

    phone  the first push at once (the app's own loud channel), then a ringing push every 30-60 s until someone answers;
           tapping the ringing one starts a call in that room, and the call's Dan says why he called (voice_sideband)
    call   when the owner is already on a call, nothing rings: the call's Dan says it at once
    PC     the dashboard shows a banner and plays a tone while a summons is open (GET /api/v1/summon/active)

It ends when the owner answers (writes in that room, taps the notification, a call takes it up), when Dan resolves it, or
at its deadline. The ringing runs in a process of its own (``python -m app.services.owner_summon ring <id>``) so it
outlives the turn and the MCP server that asked for it.

    ~/.dan/summons/<id>.json   {id, user_id, room_id, project_id, reason, created, deadline, state, spoken, pushes, ...}
    state: open -> answered | resolved | expired
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)
ROOT = Path(os.environ.get('DAN_SUMMON_ROOT') or Path.home()/'.dan'/'summons')
LOG = Path(__file__).resolve().parents[2]/'.tmp'/'owner-summon.log'
CHANNEL = 'dan-summon'          # created by the phone app (1.0.82+) with the ring sound below; older apps fall back
SOUND = 'dan_ring.wav'
RING_AFTER = (30, 30, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60)   # seconds between pushes after the first
DEFAULT_MINUTES, MAX_MINUTES = 5, 15

TOOL = {
    'name': 'summon',
    'description': (
        '本人を今すぐ呼ぶ。チャットに書くだけでは間に合わない時に使う。スマホに大きな音の通知を出し、反応が無ければ30〜60秒ごとに鳴らし直す'
        '（押すとその部屋で通話が始まり、通話のダンが呼んだ理由を言う）。本人が通話中なら鳴らさず、通話のダンがすぐ言う。PCの画面にも出る。'
        '本人がこの部屋に書く・通知を押す・通話で受ける・resolve・期限のどれかで止まる。\n'
        '【呼ぶ時（これ以外では呼ばない）】本人が今応じないと作業が失敗する、または期限がある時だけ。例: 振込や決済の承認'
        '（スマート認証NEO・6桁の承認番号・3Dセキュア）、本人のスマホにだけ届くSMSや認証コード、スマホでのログイン承認、'
        '数分で切れる確認画面、画像認証など本人の手が要る画面で止まった時。これらで待ちに入るその時に呼ぶ（チャットに書いて待つだけにしない）。\n'
        '【呼ばない】作業が終わった・判断や承認がほしいだけで期限が無い（普段の返事と通知で足りる）、途中経過、裏の直し、'
        '本人が「知らせなくていい」と言った種類。夜中でも上の「呼ぶ時」なら呼ぶ。\n'
        '【書き方】reason は本人がスマホの通知1行で読んで、すぐ動ける文。何を・どこで・数字は全部（例:「振込300,100円の承認をスマート認証NEOで押してください。番号は483920」）。'
        '番号は全桁を写す。期限が分かれば deadline_minutes（既定5分・最長15分）。'
        '本人が応じて待ちが解けたら、同じ作業の中で action=resolve（id を省くとこの部屋の呼び出しを全部止める）。'
    ),
    'input_schema': {'type': 'object', 'properties': {
        'action': {'type': 'string', 'enum': ['call', 'resolve', 'status'], 'description': 'call=呼ぶ（既定）/ resolve=止める / status=今の呼び出し'},
        'reason': {'type': 'string', 'description': 'call: 本人に何をしてほしいか（通知にそのまま出て、通話でも言う）'},
        'deadline_minutes': {'type': 'integer', 'minimum': 1, 'maximum': MAX_MINUTES, 'description': 'call: 何分で切れるか（既定5）'},
        'id': {'type': 'string', 'description': 'resolve: 止める呼び出し（省くとこの部屋の全部）'},
    }, 'additionalProperties': False},
}


def _path(summon_id):
    return ROOT/(str(uuid.UUID(summon_id))+'.json')


def read(summon_id):
    try:
        return json.loads(_path(summon_id).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _write(s):
    ROOT.mkdir(parents=True, exist_ok=True)
    path = _path(s['id'])
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(s, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


def _change(summon_id, fn):
    s = read(summon_id)
    if s is None:
        return None
    fn(s)
    _write(s)
    return s


def _all():
    if not ROOT.exists():
        return []
    out = []
    for p in ROOT.glob('*.json'):
        try:
            out.append(json.loads(p.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda s: s.get('created', 0))


def _expire(s, now=None):
    """An open summons past its deadline is expired (written back, so every reader agrees)."""
    if s.get('state') == 'open' and (now or time.time()) >= s.get('deadline', 0):
        s = _change(s['id'], lambda x: x.update(state='expired', ended=time.time())) or s
    return s


def live(user_id=None, room_id=None):
    """Summonses that still matter: open, or answered by a tap but not yet said on a call, within their deadline."""
    now = time.time()
    out = []
    for s in _all():
        if user_id and s.get('user_id') != user_id: continue
        if room_id and s.get('room_id') != room_id: continue
        s = _expire(s, now)
        if s.get('state') == 'open' or (s.get('state') == 'answered' and not s.get('spoken') and now < s.get('deadline', 0)):
            out.append(s)
    return out


def answer(summon_id, by):
    """The owner reacted (tap, a message in the room, a call). Ringing stops; a call may still say it."""
    return _change(summon_id, lambda s: s.update(state='answered', answered_by=by, ended=time.time()) if s.get('state') == 'open' else None)


def answer_room(room_id, by='message'):
    n = 0
    for s in live(room_id=room_id):
        if s.get('state') == 'open':
            answer(s['id'], by); n += 1
    return n


def resolve(room_id=None, summon_id=None):
    n = 0
    for s in ([read(summon_id)] if summon_id else live(room_id=room_id)):
        if s and s.get('state') in ('open', 'answered'):
            _change(s['id'], lambda x: x.update(state='resolved', ended=time.time())); n += 1
    return n


def mark_spoken(summon_id):
    return _change(summon_id, lambda s: s.update(spoken=True, state='answered' if s.get('state') == 'open' else s.get('state'),
                                                 answered_by=s.get('answered_by') or 'call', ended=s.get('ended') or time.time()))


def _project_of(room_id):
    try:
        from app.services.supabase_client import get_supabase_client
        rows = get_supabase_client().client.table('projects').select('id,title,metadata,origin_room_id').eq('room_id', room_id).limit(1).execute().data or []
        if not rows:
            return '', ''
        row = rows[0]
        # a hidden room (a dev-lead board discussion) opens its origin room on the phone, like ordinary pushes do
        if (row.get('metadata') or {}).get('hidden') and row.get('origin_room_id'):
            origin = get_supabase_client().client.table('projects').select('id,title').eq('room_id', row['origin_room_id']).limit(1).execute().data or []
            if origin:
                return origin[0]['id'], origin[0].get('title') or ''
        return row['id'], row.get('title') or ''
    except Exception:
        logger.exception('project lookup failed room=%s', room_id)
        return '', ''


def _in_call(user_id):
    """A call of this owner is going (any room): the call's Dan says the summons instead of the phone ringing."""
    from app.services import voice_calls
    try:
        for p in voice_calls.ROOT.glob('*.json'):
            if p.name.endswith('.inbox.jsonl'): continue
            call = voice_calls.active(p.stem)
            if call and (not call.get('user_id') or call.get('user_id') == user_id):
                return True
    except Exception:
        pass
    return False


def create(user_id, room_id, reason, minutes=DEFAULT_MINUTES):
    minutes = max(1, min(MAX_MINUTES, int(minutes or DEFAULT_MINUTES)))
    project_id, title = _project_of(room_id)
    now = time.time()
    s = {'id': str(uuid.uuid4()), 'user_id': user_id, 'room_id': room_id, 'project_id': project_id, 'title': title,
         'reason': reason.strip()[:400], 'created': now, 'deadline': now + minutes*60, 'state': 'open', 'spoken': False, 'pushes': []}
    _write(s)
    return s


def start_ringing(summon_id):
    """The ringing outlives this turn and this process."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    root = str(Path(__file__).resolve().parents[2])
    with open(LOG, 'a') as out:
        subprocess.Popen([sys.executable, '-m', 'app.services.owner_summon', 'ring', summon_id], cwd=root,
                         stdout=out, stderr=out, stdin=subprocess.DEVNULL, start_new_session=True,
                         env={**os.environ, 'PYTHONPATH': root})


async def _push(s, ring):
    from app.services.push_service import get_push_service
    url = f"/chat/{s['project_id']}" if s.get('project_id') else '/chat'
    title = 'ダンが呼んでいます' if not ring else 'ダンが呼んでいます（応答してください）'
    data = {'summon_id': s['id'], 'room_id': s['room_id'], 'call': bool(ring)}
    return await get_push_service().notify_room(room_id=f"user:{s['user_id']}", exclude_type='ai', title=title,
                                                body=s['reason'][:180], url=url, data=data, channel_id=CHANNEL, sound=SOUND)


async def ring(summon_id):
    """First push now, then ringing pushes until answered, resolved or the deadline. Silent while a call is going."""
    waits = iter(RING_AFTER)
    first = True
    while True:
        s = read(summon_id)
        if not s or _expire(s).get('state') != 'open':
            return
        if not _in_call(s['user_id']):
            try:
                result = await _push(s, ring=not first)
            except Exception as exc:
                result = {'error': type(exc).__name__}
            _change(summon_id, lambda x: x['pushes'].append({'at': time.time(), 'ring': not first, 'result': result}))
            first = False
        wait = next(waits, None)
        if wait is None:
            return
        end = time.time() + wait
        while time.time() < end:   # stop within a second of an answer
            await asyncio.sleep(1)
            s = read(summon_id)
            if not s or s.get('state') != 'open':
                return


async def tool(params, user_id, room_id):
    params = params or {}
    action = params.get('action') or 'call'
    if action == 'status':
        return {'success': True, 'output': json.dumps([{k: s.get(k) for k in ('id', 'reason', 'state', 'created', 'deadline')}
                                                        for s in live(room_id=room_id)], ensure_ascii=False)}
    if action == 'resolve':
        n = resolve(room_id=room_id, summon_id=params.get('id'))
        return {'success': True, 'output': f'{n}件の呼び出しを止めた'}
    reason = str(params.get('reason') or '').strip()
    if not reason:
        return {'success': False, 'error': 'reason（本人に何をしてほしいか）を書く'}
    if not user_id or not room_id:
        return {'success': False, 'error': '部屋が分からないので呼べない'}
    for old in live(room_id=room_id):   # one summons per room: a new reason replaces the old one
        if old.get('state') == 'open': resolve(summon_id=old['id'])
    s = create(user_id, room_id, reason, params.get('deadline_minutes') or DEFAULT_MINUTES)
    calling = _in_call(user_id)
    start_ringing(s['id'])
    how = '本人は通話中なので、通話のダンがすぐ伝える' if calling else 'スマホに音つきで知らせ、反応が無ければ鳴らし直す'
    return {'success': True, 'output': f"呼んだ（id={s['id']}、{how}。期限 {time.strftime('%H:%M', time.localtime(s['deadline']))}）。"
                                       '待ちが解けたら action=resolve で止める。本人がこの部屋に書いた時は自動で止まる。'}


def main(argv):
    if len(argv) >= 2 and argv[0] == 'ring':
        logging.basicConfig(level=logging.INFO)
        try:
            from app.services import inbox
            inbox._env()   # Supabase keys from .env for this lone process
        except Exception:
            pass
        asyncio.run(ring(argv[1]))
        return 0
    print('usage: python -m app.services.owner_summon ring <id>')
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
