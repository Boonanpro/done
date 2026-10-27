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
    }

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
