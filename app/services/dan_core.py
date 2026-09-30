"""Dan's one core (the harness every surface shares): what Dan is told about the owner, about Dan, and how Dan works.

Until 2026-09-30 there were three Dans with three different briefs: chat Dan (the Claude CLI) read about 17,000
characters (the owner, the persona, how Dan operates, the saved information, the browser rules, the workspace rules); the
voice backend read 1,900 characters of voice rules and a tool list; the worker that does the work asked for in a call read
1,300 characters. So work asked for by voice was done by a Dan that knew little of the owner or of how chat Dan works,
and the owner found that voice could not do what chat could.

shared() is the chat brief itself (the same builder chat uses), minus the list of the CLI's own tools (the other surfaces
get Dan's tool catalog instead), plus the workspace rules the CLI reads on its own from its folder. Each surface adds only
its own few rules on top: voice (spoken answers, the Live delegation), the worker (a job's rules).
"""
import re
import time

from app.agent.cli_runner import CLI_WORKSPACE

CACHE_SECONDS = 600
_cache = {}


def _owner_words(room_id, user_id):
    """A few of the owner's own recent messages (this room first, else anywhere): what the language rule is read from."""
    from app.services.supabase_client import get_supabase_client
    table = get_supabase_client().client.table('chat_messages')
    for scope in (('room_id', room_id), ('sender_id', user_id)):
        if not scope[1]:
            continue
        try:
            rows = table.select('content').eq(scope[0], scope[1]).eq('sender_type', 'human').order('created_at', desc=True).limit(5).execute().data
        except Exception:
            rows = []
        words = '\n'.join(str(r.get('content') or '')[:300] for r in rows or [])
        if words.strip():
            return words
    return ''


def shared(room_id, user_id, title='', description=''):
    """The brief every surface of this room gets. Built from the chat's own builder, kept for CACHE_SECONDS (the saved
    information and the room's role change rarely; a call or a job reuses it instead of rebuilding)."""
    key = (room_id, user_id)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    from app.agent.cli_runner import _build_system_prompt
    # The brief's language rule is detected from what the owner wrote. Built without it, it said "English" and the voice
    # backend answered a Japanese owner in English (2026-09-30 measurement).
    brief = _build_system_prompt(title, description, 'in_progress', user_messages=_owner_words(room_id, user_id),
                                 room_id=room_id or '', user_id=user_id or '', include_room_role=bool(room_id and user_id))
    # the CLI's own tool list (built-in tools, MCP names, skills): the other surfaces get Dan's catalog with the same tools
    brief = re.sub(r'(?ms)^## Available Tools\n.*?(?=^## )', '', brief).strip()
    try:
        rules = (CLI_WORKSPACE / 'CLAUDE.md').read_text(encoding='utf-8').strip()
    except OSError:
        rules = ''
    text = brief + ('\n\n# ダンの作業のきまり（チャットのダンと同じ）\n\n' + rules if rules else '')
    _cache[key] = (time.monotonic(), text)
    return text
