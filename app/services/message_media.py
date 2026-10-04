"""Files named in Dan's messages become what the owner's screen shows: images and videos inside the chat, other files as
a link that opens. The chat screen (project-chat-panel parseMediaContent) shows [添付画像: url], [添付動画: name (url)] and
[添付ファイル: name (url)]; a bare path shows nothing it can open.

Why here and not in the prompts (2026-09-27): whether a report showed its files depended on how the job model happened to
write them. One report attached its PDF and images; the next wrote `/api/v1/files/…pdf` and `http://127.0.0.1:3000/…` in
plain text, the owner saw neither, asked 「出して」 and waited half an hour. Every write of a Dan message passes here.
"""
import re

IMAGE = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
VIDEO = {'mp4', 'mov', 'webm', 'm4v', 'mkv', 'avi'}

_MARKUP = re.compile(r'\[添付(?:画像|動画|ファイル): [^\]\n]*\]')
_FENCE = re.compile(r'```[\s\S]*?```')
_MD_LINK = re.compile(r'!?\[[^\]\n]*\]\([^)\s]*\)')
# a served file: /api/v1/files/<name>, also written with the PC's own address, or as the folder it is served from
_FILE = re.compile(r'`?(?:https?://(?:127\.0\.0\.1|localhost)(?::\d+)?)?/api/v1/files/([^\s)\]`\'"<>（）、。]+)`?'
                   r'|`?[A-Za-z]:[\\/]done[\\/]uploads[\\/]([^\s)\]`\'"<>（）、。\\/]+)`?')
_LOCAL_LINK = re.compile(r'\((?:https?://(?:127\.0\.0\.1|localhost)(?::\d+)?)(/api/v1/files/[^)\s]+)\)')
_LOCAL_HOST = re.compile(r'https?://(?:127\.0\.0\.1|localhost)(?::\d+)?(?=/api/v1/files/)')
_FENCE_SPLIT = re.compile(r'(```[\s\S]*?```)')


def markup(name):
    url = f'/api/v1/files/{name}'
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if ext in IMAGE:
        return f'[添付画像: {url}]'
    if ext in VIDEO:
        return f'[添付動画: {name} ({url})]'
    return f'[添付ファイル: {name} ({url})]'


def portable(text):
    """A served file's PC-only address (http://localhost:8000/api/v1/files/…) made relative; code blocks kept as written.

    Why (2026-10-04): the phone draws a reply from its turn blocks, not from content. A block still said
    `[添付動画: … (http://localhost:8000/api/v1/files/….mp4)]`; the PC opened it at once, the phone waited on a port
    that is closed from outside. Applied to every text block that is saved."""
    if not text or '/api/v1/files/' not in text:
        return text
    return ''.join(p if p.startswith('```') else _LOCAL_HOST.sub('', p) for p in _FENCE_SPLIT.split(text))


def normalize(content):
    """The message with each bare served-file mention turned into the chat's attachment form. Existing attachments,
    markdown links/images (their PC address made relative) and code blocks are kept as written. A file already attached
    elsewhere in the message is named, not attached twice."""
    if not content or ('/api/v1/files/' not in content and 'uploads' not in content):
        return content
    kept = []

    def hold(match):
        kept.append(match.group(0))
        return f'\x00{len(kept) - 1}\x00'

    text = _FENCE.sub(hold, content)
    text = _LOCAL_LINK.sub(lambda m: '(' + m.group(1) + ')', text)
    text = _MARKUP.sub(lambda m: _LOCAL_HOST.sub('', m.group(0)), text)
    attached = set(re.findall(r'/api/v1/files/([^\s)\]]+)', ' '.join(_MARKUP.findall(text))))
    text = _MARKUP.sub(hold, text)
    text = _MD_LINK.sub(hold, text)

    def convert(match):
        name = (match.group(1) or match.group(2) or '').rstrip('.,;:')
        if not name:
            return match.group(0)
        if name in attached:
            return name
        attached.add(name)
        return '\n' + markup(name) + '\n'

    text = _FILE.sub(convert, text)
    text = re.sub(r'\x00(\d+)\x00', lambda m: kept[int(m.group(1))], text)
    return re.sub(r'\n{3,}', '\n\n', text)
