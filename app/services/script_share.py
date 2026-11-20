"""The link the owner sends to the other side from the /script-listen screen (11/20 本人「URL共有できるコピーボタン」
「これまで通り相手が編集したりコメントしたりできるドキュメントで」).

The working doc keeps the owner's comments and suggestions, so the link is the customer's copy of it
(app/services/gdoc_client.py): the confirmed text only, no comments, anyone with the link can edit and comment.
The first press makes the copy; later presses give the same link. When the working doc moved on since the
copy was last updated, the screen offers to update it first (the changes show to the customer as suggestions).
"""
import json
import re

from app.services import gdoc_client as C
from app.services import gdoc_events as E
from app.services import script_listen as S


def _url(client_id):
    return f'https://docs.google.com/document/d/{client_id}/edit'


def _copy_of(work_id):
    """The customer's copy registered for this working doc (the newest one when there are several)."""
    best = None
    for meta_path in (E.ROOT / 'client').glob('*/meta.json'):
        try: meta = json.loads(meta_path.read_text())
        except (OSError, ValueError): continue
        if meta.get('work') != work_id: continue
        when = meta.get('delivered_at') or meta.get('adopted_at') or ''
        if best is None or when > (best.get('delivered_at') or best.get('adopted_at') or ''):
            best = meta
    return best


def _confirmed(account, work_id):
    from app.services.gdoc_drive import export_docx
    work = export_docx(account, work_id)
    return C._norm(C.texts(C.clean(work), 'after')), C.pending_suggestions(work)


def state(work_id):
    """Is there a link yet, and does it show what the working doc says now."""
    account = S._account(work_id)
    meta = _copy_of(work_id)
    if not meta:
        _, pending = _confirmed(account, work_id)
        return {'url': None, 'behind': False, 'pending': pending}
    now, pending = _confirmed(account, work_id)
    return {'url': _url(meta['client']), 'client': meta['client'], 'behind': now != C._norm(meta['published_after']),
            'pending': pending, 'updated_at': meta.get('delivered_at') or meta.get('adopted_at')}


def _share_by_link(account, client_id, work_id):
    """Anyone with the link can edit and comment (not findable by search), in the same folder as the working doc."""
    from app.services.gdoc_drive import request
    request(account, 'POST', f'files/{client_id}/permissions',
            body={'type': 'anyone', 'role': 'writer', 'allowFileDiscovery': False}, params={'sendNotificationEmail': 'false'})
    parents = request(account, 'GET', f'files/{work_id}', params={'fields': 'parents'}).get('parents') or []
    if parents:
        now = request(account, 'GET', f'files/{client_id}', params={'fields': 'parents'}).get('parents') or []
        request(account, 'PATCH', f'files/{client_id}',
                params={'addParents': ','.join(parents), 'removeParents': ','.join(p for p in now if p not in parents)})


def share(work_id, update=False):
    """Make the customer's copy on the first press; with update, put the working doc's confirmed text into it."""
    from app.services.gdoc_drive import request
    account = S._account(work_id)
    meta = _copy_of(work_id)
    if not meta:
        name = request(account, 'GET', f'files/{work_id}', params={'fields': 'name'}).get('name') or '台本'
        name = re.sub(r'\s*第\s*\d+\s*稿\s*$', '', name).strip() or name
        result = C.deliver(account, work_id, None, name, allow_pending=True)
        _share_by_link(account, result['client'], work_id)
        return {**state(work_id), 'made': True}
    if update:
        try:
            C.deliver(account, work_id, meta['client'], allow_pending=True)
        except ValueError as exc:
            if 'customer changed or commented' in str(exc):
                raise S.ListenError('相手が共有用のドキュメントを直したかコメントしているので、更新を止めました。'
                                    'ダンに「共有用の直しを取り込んで」と頼んでください。', 409) from exc
            raise
        return {**state(work_id), 'updated': True}
    return state(work_id)
