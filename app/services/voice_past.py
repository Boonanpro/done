"""「この前の新幹線、結局キャンセルできたんだっけ」: a question about something said or done before.

It used to become a delegated job (median 31s, 2m13s in the owner's test) or, worse, a list of jobs that made the
speech model ask the owner to repeat what they had already told Dan. The records are a keyword search away: gather
them in about a second across every room of the owner, plus recent job results, and let the reader answer.
Read-only. Nothing here leaves the machine except to the reader model that already receives the conversation."""
import asyncio
import re
import time
from datetime import datetime, timedelta, timezone

# Words that carry no topic: fillers, question endings, time words that never appear in the record itself.
STOP = set('この前 こないだ 先週 昨日 今日 明日 さっき 結局 ちゃんと 普通 登録 情報 確認 お前 あれ それ これ どう なった だっけ できた 教えて 言ってた '
           'やりとり 話 件 あの その ダン 前 後 時 方 感じ 全部 本当 場合 以前 最近 いつ どこ なに 何 誰'.split())
TOKEN = re.compile(r'[一-鿿々]{2,}|[ァ-ヶー]{3,}|[A-Za-z][A-Za-z0-9.+-]{1,}|\d{1,2}月\d{1,2}日|\d{3,}')


def keywords(utterance, dialogue, limit=5):
    """Topic words of the question, the latest utterance first, then the owner's previous turns for 「それ」「あの件」."""
    seen = []
    turns = [utterance]+[r['text'] for r in reversed(dialogue[:-1]) if r.get('role') == 'user'][:2]
    for text in turns:
        for word in TOKEN.findall(text):
            if word not in STOP and word not in seen: seen.append(word)
    return seen[:limit]


def _search(user_id, word, since):
    from app.services.chat_service import ChatService
    db = ChatService().supabase
    rooms = [r['room_id'] for r in db.table('chat_room_members').select('room_id').eq('user_id', user_id).execute().data or []]
    if not rooms: return []
    escaped = word.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    rows = db.table('chat_messages').select('id,room_id,sender_type,content,created_at').in_('room_id', rooms[:400]) \
        .ilike('content', f'%{escaped}%').gte('created_at', since).order('created_at', desc=True).limit(25).execute().data or []
    return rows


async def gather(user_id, utterance, dialogue, jobs=(), days=45, budget=4.0):
    """{'keywords':[...], 'records':[{at,who,text}], 'jobs':[...]} within `budget` seconds; records may be empty."""
    words = keywords(utterance, dialogue)
    since = (datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
    started = time.monotonic()
    found = await asyncio.gather(*(asyncio.wait_for(asyncio.to_thread(_search, user_id, w, since), budget) for w in words), return_exceptions=True)
    score = {}; rows = {}
    for word, result in zip(words, found):
        if isinstance(result, BaseException): continue
        for r in result:
            text = r.get('content') or ''
            if text.startswith('【あなたの依頼・Done経由】'): continue   # the relayed copy of a voice request, not a record of what happened
            rows[r['id']] = r; score[r['id']] = score.get(r['id'], 0)+1
    # A record that mentions more of the topic words first, the newer one first among equals.
    ranked = list(rows.values())
    ranked.sort(key=lambda r: (score[r['id']], r.get('created_at') or ''), reverse=True)
    records = [{'at': (r.get('created_at') or '')[:16], 'who': {'human': 'user', 'ai': 'dan'}.get(r.get('sender_type'), r.get('sender_type')),
                'text': (r.get('content') or '')[:700]} for r in ranked[:12]]
    recent = [{'task': s.get('task', '').split('参考の直前会話')[0][:300], 'state': s.get('state'), 'result': str(s.get('result') or '')[:900]}
              for s in list(jobs)[:4] if s.get('result') or s.get('state') not in ('completed', 'failed', 'cancelled')]
    return {'keywords': words, 'records': records, 'jobs': recent, 'elapsed_ms': round((time.monotonic()-started)*1000)}
