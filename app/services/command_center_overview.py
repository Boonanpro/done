"""Read conversations directly. Interpretation belongs to Dan."""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
from app.services.project_service import ProjectService

FIELDS = 'id,room_id,content,sender_type,created_at'

def project_summary(p):
    return {k: p.get(k) for k in ('id', 'title', 'room_id', 'summary', 'has_active_run', 'last_message_at')}

async def recent_conversations(user_id, *, days=30, limit=20, offset=0):
    service = ProjectService()
    projects = [p for p in await service.list_projects(user_id)
        if p.get('room_id') and (p.get('metadata') or {}).get('role') != 'command_center']
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    sem = asyncio.Semaphore(8)
    async def activity(p):
        async with sem:
            try:
                def read():
                    return service.supabase.table('chat_messages').select('created_at').eq(
                        'room_id', p['room_id']).eq('sender_type', 'human').order('created_at', desc=True).limit(1).execute().data or []
                rows = await asyncio.to_thread(read)
                at = rows[0]['created_at'] if rows else ''
                return {**p, 'last_user_message_at': at} if p.get('has_active_run') or at >= since else None
            except Exception:
                return {**p, 'error': 'activity_unavailable'}
    eligible = [p for p in await asyncio.gather(*(activity(p) for p in projects)) if p]
    eligible.sort(key=lambda p: (bool(p.get('has_active_run')), p.get('last_user_message_at', '')), reverse=True)
    async def history(p):
        base = project_summary(p)
        if p.get('error'):
            return {**base, 'error': p['error']}
        async with sem:
            try:
                def read():
                    return service.supabase.table('chat_messages').select(FIELDS).eq(
                        'room_id', p['room_id']).order('created_at', desc=True).limit(4).execute().data or []
                messages = await asyncio.to_thread(read)
                from app.services.command_cards import outbound_cards
                return {**base, 'last_user_message_at': p['last_user_message_at'], 'messages': list(reversed(messages)),
                        'outbound': await outbound_cards(p['room_id'])}
            except Exception:
                return {**base, 'error': 'history_unavailable'}
    rows = await asyncio.gather(*(history(p) for p in eligible[offset:offset + limit]))
    return {'projects': rows, 'total': len(eligible), 'since': since, 'messages_per_room': 4,
        'next_offset': offset + limit if offset + limit < len(eligible) else None}

async def search_conversations(user_id, terms, *, limit=10, offset=0, project_id=None):
    """Content search in owned rooms, including old conversations."""
    service = ProjectService()
    # The hub also contains completed work. Excluding it makes requests such as
    # "the reservation we made here" impossible to retrieve through search.
    # Search needs owned room IDs, not dashboard unread counts and active-run
    # enrichment (several additional database round trips).
    def owned_projects():
        query = service.supabase.table('projects').select('id,room_id,title,description,summary,metadata,updated_at').eq('user_id', user_id)
        if project_id: query = query.eq('id', project_id)
        return query.execute().data or []
    projects = [p for p in await asyncio.to_thread(owned_projects) if p.get('room_id')]
    if project_id:
        projects = [p for p in projects if p['id'] == project_id]
        if not projects:
            raise ValueError('対象プロジェクトが見つからないか、アクセス権がありません')
    by_room = {p['room_id']: p for p in projects}
    if not by_room:
        return {'projects': [], 'next_offset': None}
    terms = list(dict.fromkeys(t.strip() for t in terms if t.strip()))[:6]
    if not terms:
        raise ValueError('話の内容から検索語を指定してください')
    matches = {}
    for p in projects:
        text = ' '.join(str(p.get(k) or '') for k in ('title', 'description', 'summary')).casefold()
        hits = {t for t in terms if t.casefold() in text}
        if hits:
            matches[p['room_id']] = {'terms': hits, 'messages': {}}
    async def search(term):
        # Separate ilike parameters prevent query-operator injection; escape wildcards.
        pattern = '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        def read():
            return service.supabase.table('chat_messages').select(FIELDS).in_('room_id', list(by_room)).ilike(
                'content', pattern).order('created_at', desc=True).range(offset, offset + 99).execute().data or []
        return term, await asyncio.to_thread(read)
    found = await asyncio.gather(*(search(t) for t in terms))
    for term, messages in found:
        for m in messages:
            if m['room_id'] not in by_room:
                continue
            entry = matches.setdefault(m['room_id'], {'terms': set(), 'messages': {}})
            entry['terms'].add(term)
            entry['messages'][m['id']] = m
    ranked = sorted(matches, key=lambda r: (len(matches[r]['terms']), max((m['created_at'] for m in matches[r]['messages'].values()),default=by_room[r].get('updated_at') or '')), reverse=True)
    rows = []
    for room in ranked[:limit]:
        entry = matches[room]
        recent = sorted(entry['messages'].values(), key=lambda m: m['created_at'], reverse=True)
        # Repeated follow-up questions must not crowd the original result out
        # of discovery. Include recent context and the strongest term matches.
        relevant = sorted(recent, key=lambda m: sum(t.casefold() in (m.get('content') or '').casefold() for t in terms), reverse=True)
        messages = list({m['id']: m for m in recent[:2] + relevant[:3]}.values())
        rows.append({**project_summary(by_room[room]), 'project_id': by_room[room]['id'],
            'matched_terms': sorted(entry['terms']), 'messages': [search_excerpt(m, terms) for m in messages]})
    # A matching answer without the ensuing conversation can miss a correction
    # or cancellation that doesn't repeat the search terms. Return two nearby
    # exchanges for the strongest answer in the top matches, in one parallel
    # read round, rather than making the agent discover that context blindly.
    async def context(row):
        candidates=list(matches[row['room_id']]['messages'].values())
        answers=[m for m in candidates if m.get('sender_type') in ('ai','assistant')]
        if not answers:return
        anchor=max(answers,key=lambda m:(sum(t.casefold() in (m.get('content') or '').casefold() for t in terms),m['created_at']))
        def read():
            return service.supabase.table('chat_messages').select(FIELDS).eq('room_id',row['room_id']).gt(
                'created_at',anchor['created_at']).order('created_at').limit(4).execute().data or []
        following=await asyncio.to_thread(read)
        row['following_context']={'after_message_id':anchor['id'],'messages':[search_excerpt(m,terms) for m in following]}
    await asyncio.gather(*(context(row) for row in rows[:2]))
    return {'projects': rows, 'terms': terms, 'matching_projects': len(ranked),
        'next_offset': offset + 100 if any(len(ms) == 100 for _, ms in found) else None}


def search_excerpt(message, terms, budget=1800):
    """Bound discovery results around matches; full originals remain readable."""
    text = message.get('content') or ''
    if len(text) <= budget:
        return message
    folded = text.casefold()
    position = min((folded.find(t.casefold()) for t in terms if t.casefold() in folded), default=0)
    start = max(0, position - budget // 3)
    end = min(len(text), start + budget)
    return {**message, 'content': ('[…]' if start else '') + text[start:end] + ('[…]' if end < len(text) else ''),
        'truncated': True, 'content_length': len(text)}
