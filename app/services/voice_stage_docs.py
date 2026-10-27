"""Documents of the owner's sites on the call's stage: articles of the X operation room, scripts of the script room,
written, revised and published by voice (voice_stage, 2026-10-27, the owner: "X運用室とかみたいにダンが作った成果物でも
そういうことができて X の記事投稿とか出来たらまじジャービス").

Dan's code names no site. A site that wants its documents on the stage declares, in its `_server/routes.py` (the module
app/services/artifact_backends.py mounts), a `STAGE_DOCUMENTS` dict:

    STAGE_DOCUMENTS = {
        'kinds': {'x_article': {'label': 'X の記事', 'publish': 'X に投稿する', 'accounts': ['OYmpa7', ...]}, ...},
        'create':  lambda user_id, kind, title, body, account, note: doc,
        'revise':  lambda user_id, doc_id, title, body: doc,
        'read':    lambda user_id, doc_id: doc,
        'publish': lambda user_id, doc_id: doc,     # optional; a kind without it is only written and revised here
        'page':    lambda user_id, doc_id: '/preview/<slug>?…',   # optional: the site's own screen opened on that document
        'assist':  lambda user_id, doc_id, instruction: {...},    # optional: the request handed to the site's own assistant
        'assist_state': lambda user_id, doc_id, request_id: {...},  # optional: how that request stands
    }

The owner on 2026-10-27: everything on the stage must be the real screen, and a revision must go through the site's own
editing assistant (the X room's reads the X writing skill), not text the call rewrote by itself. A site with `page` is
shown on the stage as that page (a frame of this site, signed in as the owner), and a site with `assist` gets the owner's
words as they were said; its assistant writes and lays its suggestions on that screen, where the owner approves them
(by a tap, or by voice: the stage passes the command to the page, which runs its own approve button). assist_state
answers {'state': 'queued'|'running'|'done'|'error', 'message': the assistant's reply, 'changes': whether it changed the
text, 'pending': suggestions on the screen not yet approved or refused}.

A doc is a plain dict: {'id', 'kind', 'title', 'body', 'status': 'draft'|'publishing'|'published'|'failed', 'revision',
'account', 'url', 'error'}. A function may be synchronous (it talks to the database; it runs in a thread) or a coroutine
function (a site's publish path that is itself async runs in this loop). Publishing
is the site's own send path with its own checks (the X room's publish_send verifies the digest of what was shown); this
module adds nothing to that path but the stage's approval gate (Stage.publish_document: the read-back and the owner's
spoken approval, judged on the transcript by the server).

The sideband that runs the stage lives in the sandbox (voicelog_routes), the process that mounts the sites' routes, so
the providers are reached in this process. A test server (work.py try) mounts the same way."""
import asyncio
import inspect
import logging

logger = logging.getLogger(__name__)

STATUSES = ('draft', 'publishing', 'published', 'failed')
_extra = {}   # kind -> provider, registered by tests (or anything that is not a site)


def providers():
    """kind -> the provider that owns it, from every mounted site that declares STAGE_DOCUMENTS."""
    found = dict(_extra)
    try:
        from app.services import artifact_backends
        mounted = artifact_backends._mounted
    except Exception:   # noqa: BLE001 - no sites in this process
        mounted = {}
    for slug, entry in list(mounted.items()):
        module = (entry or {}).get('module')
        spec = getattr(module, 'STAGE_DOCUMENTS', None)
        if not isinstance(spec, dict) or not isinstance(spec.get('kinds'), dict): continue
        for kind in spec['kinds']:
            found[kind] = dict(spec, slug=slug)
    return found


def register(kind, provider):
    """A provider outside the sites (tests)."""
    _extra[kind] = provider


def kinds():
    """What the voice backend may ask for: kind -> {label, publish, accounts}."""
    out = {}
    for kind, spec in providers().items():
        info = dict((spec.get('kinds') or {}).get(kind) or {})
        info['publishable'] = bool(spec.get('publish')) and bool(info.get('publish'))
        info['assistant'] = bool(spec.get('assist'))
        out[kind] = info
    return out


def normal(doc, kind=''):
    """The doc as the stage keeps it: every field present, strings where strings are expected."""
    doc = dict(doc or {})
    status = str(doc.get('status') or 'draft')
    return {'id': str(doc.get('id') or ''), 'kind': str(doc.get('kind') or kind), 'title': str(doc.get('title') or ''),
            'body': str(doc.get('body') or ''), 'status': status if status in STATUSES else 'draft',
            'revision': int(doc.get('revision') or 1), 'account': str(doc.get('account') or ''), 'url': str(doc.get('url') or ''),
            'error': str(doc.get('error') or '')}


async def _call(fn, *args):
    if inspect.iscoroutinefunction(fn): return await fn(*args)
    out = await asyncio.to_thread(fn, *args)
    return await out if inspect.isawaitable(out) else out


def _provider(kind):
    spec = providers().get(kind)
    if spec is None: raise LookupError(f'「{kind}」という種類の文書を出せる成果物が無い。出せるのは: ' + '、'.join(kinds()) if kinds() else 'この通話では文書を出せる成果物が無い。')
    return spec


async def create(user_id, kind, title, body, account='', note=''):
    spec = _provider(kind)
    doc = await _call(spec['create'], user_id, kind, title, body, account, note)
    return normal(doc, kind)


async def revise(user_id, kind, doc_id, title=None, body=None):
    spec = _provider(kind)
    doc = await _call(spec['revise'], user_id, doc_id, title, body)
    return normal(doc, kind)


async def read(user_id, kind, doc_id):
    spec = _provider(kind)
    doc = await _call(spec['read'], user_id, doc_id)
    return normal(doc, kind)


async def publish(user_id, kind, doc_id):
    spec = _provider(kind)
    if not spec.get('publish'): raise LookupError(f'{kind} は通話からは公開できない（作る・直すまで）。')
    doc = await _call(spec['publish'], user_id, doc_id)
    return normal(doc, kind)


def can_assist(kind):
    spec = providers().get(kind)
    return bool(spec and spec.get('assist') and spec.get('assist_state'))


async def page(user_id, kind, doc_id):
    """The path of the site's own screen showing the document ('' when the site has none)."""
    spec = providers().get(kind)
    if not spec or not spec.get('page'): return ''
    path = str(await _call(spec['page'], user_id, doc_id) or '')
    return path if path.startswith('/') and not path.startswith('//') else ''


async def assist(user_id, kind, doc_id, instruction):
    spec = _provider(kind)
    if not spec.get('assist'): raise LookupError(f'{kind} には編集アシスタントが無い。')
    return dict(await _call(spec['assist'], user_id, doc_id, instruction) or {})


async def assist_state(user_id, kind, doc_id, request_id):
    spec = _provider(kind)
    if not spec.get('assist_state'): raise LookupError(f'{kind} には編集アシスタントが無い。')
    out = dict(await _call(spec['assist_state'], user_id, doc_id, request_id) or {})
    state = str(out.get('state') or 'queued')
    return {'state': state if state in ('queued', 'running', 'done', 'error') else 'running', 'message': str(out.get('message') or ''),
            'changes': bool(out.get('changes')), 'pending': int(out.get('pending') or 0), 'laid': bool(out.get('laid', True))}


async def pending(user_id, kind, doc_id):
    """Suggestions on the site's screen not yet decided (0 when the site has no assistant)."""
    spec = providers().get(kind)
    if not spec or not spec.get('assist_state'): return 0
    out = await _call(spec['assist_state'], user_id, doc_id, '')
    return int((out or {}).get('pending') or 0)
