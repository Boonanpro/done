"""The files of a room, and putting one in front of the owner in that room's chat.

Why (2026-09-27): asked 「YouTubeの方のシートが出てないから出せ」 in a call, the voice had no way to put a file in the chat.
It opened the PDF on the PC (a job, 16 minutes) and asked a second job to attach it (37 minutes). Showing a file is one
message write: these make it a voice function that answers within a second, and let the voice know what files the room has.
"""
import re
import shutil
from pathlib import Path

UPLOADS = Path(__file__).resolve().parents[2] / 'uploads'
_SERVED = re.compile(r'/api/v1/files/([^\s)\]`\'"<>（）、。]+)')


def kind(name):
    from app.services.message_media import IMAGE, VIDEO
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    return 'image' if ext in IMAGE else 'video' if ext in VIDEO else 'file'


async def listing(room_id, user_id, limit=30):
    """The files named in the room's recent messages, newest first: name, kind, when, and the words around it (which
    account, which version) so 「YouTubeの方のシート」 can be matched to a file."""
    from app.services.chat_service import ChatService
    messages = await ChatService().get_messages(room_id, user_id, limit=200)
    seen, out = set(), []
    for m in sorted(messages, key=lambda m: m.get('created_at') or '', reverse=True):
        text = m.get('content') or ''
        for found in _SERVED.finditer(text):
            name = found.group(1).rstrip('.,;:')
            if name in seen or not (UPLOADS / name).is_file():
                continue
            seen.add(name)
            lines = [l for l in text.splitlines() if name in l]
            line = next((l for l in lines if l.lstrip().startswith('[添付ファイル')), lines[0] if lines else '')
            label = re.sub(r'\[添付(?:画像|動画|ファイル): ?|\(/api/v1/files/[^)]*\)|/api/v1/files/\S+|[\]*`]', '', line).strip(' :-・')
            out.append({'name': name, 'kind': kind(name), 'at': (m.get('created_at') or '')[:16],
                        'label': label[:80], 'said_in': re.sub(r'\s+', ' ', text)[:120]})
            if len(out) >= limit:
                return out
    return out


def served_name(item):
    """The uploads name for a URL, a served path, a bare file name, or a file on this PC (copied into uploads)."""
    item = str(item or '').strip().strip('`')
    found = _SERVED.search(item)
    if found and (UPLOADS / found.group(1)).is_file():
        return found.group(1)
    if item and '/' not in item and '\\' not in item and (UPLOADS / item).is_file():
        return item
    path = Path(item)
    if path.is_absolute() and path.is_file():
        name = path.name
        if (UPLOADS / name).exists() and (UPLOADS / name).resolve() != path.resolve():
            stem, dot, ext = name.rpartition('.')
            n = 2
            while (UPLOADS / f'{stem or ext}-{n}{dot}{ext if stem else ""}').exists():
                n += 1
            name = f'{stem or ext}-{n}{dot}{ext if stem else ""}'
        if not (UPLOADS / name).exists():
            shutil.copy2(path, UPLOADS / name)
        return name
    return None


async def show(room_id, user_id, files, text=''):
    """Post the files (and a short line) as Dan's message in the room. Images and videos show inside the chat, other files
    as a link that opens. Returns what was shown and what could not be found."""
    from app.services.chat_service import ChatService
    from app.services.message_media import markup
    shown, missing, links = [], [], []
    for item in files or []:
        if re.match(r'https?://', str(item)) and '/api/v1/files/' not in str(item):
            links.append(str(item))   # an outside page: a link the owner taps
            continue
        name = served_name(item)
        (shown if name else missing).append(name or str(item))
    if not shown and not links:
        return {'shown': [], 'missing': missing}
    body = '\n'.join(filter(None, [str(text or '').strip(), *links, *[markup(n) for n in shown]]))
    message = await ChatService().send_message(room_id, user_id, body, sender_type='ai')
    return {'shown': shown + links, 'missing': missing, 'message_id': message.get('id')}
