"""The link the owner sends to the other side from the /script-listen screen (11/20 本人「URL共有できるコピーボタン」
「これまで通り相手が編集したりコメントしたりできるドキュメントで」).

The working doc keeps the owner's comments and suggestions, so the link is the customer's copy of it
(app/services/gdoc_client.py): the confirmed text only, no comments, anyone with the link can edit and comment.
The first press makes the copy; later presses give the same link. After that the copy follows the working doc by
itself (sync below).
"""
import json
import re

from app.services import gdoc_client as C
from app.services import gdoc_events as E
from app.services import script_listen as S
from app.services import script_listen_marks as M


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
    """Is there a link yet, and how the copy follows the working doc (it does by itself, 11/21)."""
    meta = _copy_of(work_id)
    if not meta:
        return {'url': None, 'auto': True}
    standing = {x['id'] for x in M.load(S.OWNER_SUGS, work_id)}
    held = [h for h in meta.get('held') or [] if h.get('id') in standing]
    return {'url': _url(meta['client']), 'client': meta['client'], 'auto': True,
            'synced_at': meta.get('synced_at') or meta.get('delivered_at') or meta.get('adopted_at'),
            'checked_at': meta.get('checked_at'), 'from_client': len(held), 'error': meta.get('sync_error'),
            'following': work_id in _timers}


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
        sync(work_id)
        return {**state(work_id), 'updated': True}
    poke(work_id, 0.5)          # opening the panel: look at the copy now
    return state(work_id)


# ---------------------------------------------------------------- keeping the customer's copy in step (11/21)
#
# 本人 11/21「読み上げれるページで俺が原本編集したら中村さんの方にもそれが反映されて書き換わる？それができることが
# 重要」. The copy follows the working doc's confirmed text by itself: a few seconds after the working doc changes, the
# paragraphs the owner changed are written into the copy in place (Docs API), so the customer's comments and what the
# customer wrote elsewhere stay. Writing the copy again from a DOCX (deliver) would wipe both, so it is not used here.
#
# What the customer changed in the copy is brought into the working doc as suggestions on the screen (owner overlay
# suggestions, by='client'); while one stands, the owner's text does not go over the customer's in the copy. Taken, the
# two read the same; taken back, the owner's text goes into the copy again.
#
# Three lists of paragraph texts: P (meta['synced']: the copy as last written), W (the working doc, confirmed text)
# and C (the copy now). Tables and paragraphs with pictures are marks that are never written.

import threading
import time as _time
from difflib import SequenceMatcher

SYNC_AFTER = 8          # seconds of quiet after a change before the copy is written
CHECK_EVERY = 30        # the screen's polling looks at the copy at most this often
_timers: dict = {}
_last_check: dict = {}
_run_lock = threading.Lock()
TABLE, PICTURE = '\x00表', '\x00画像'


def paragraphs(doc, confirmed=True):
    """Top-level paragraphs: [{i: content index, text, bm, fixed}] — ``confirmed``: suggested words left out (the
    working doc's suggestions are not the script yet), suggested deletions kept; a paragraph break that is only
    suggested joins the paragraph to the next one. ``fixed``: a table or a picture, never written."""
    out, carry = [], None
    for ci, el in enumerate(doc.get('body', {}).get('content', [])):
        if 'table' in el:
            out.append({'i': ci, 'text': TABLE, 'bm': '', 'fixed': True}); carry = None; continue
        p = el.get('paragraph')
        if p is None: continue
        chars = S._chars(p)
        if confirmed: chars = [c for c in chars if not c[2]['ins']]
        text = ''.join(c[1] for c in chars)
        bm = ''.join('1' if c[2]['bold'] else '0' for c in chars)
        fixed = any(e.get('inlineObjectElement') for e in p.get('elements', []))
        if fixed: text += PICTURE; bm += '0'
        last = next((e for e in reversed(p.get('elements', [])) if e.get('textRun')), None)
        joined = confirmed and last and last['textRun']['content'].endswith('\n') and last['textRun'].get('suggestedInsertionIds')
        if carry:
            text, bm, fixed = carry['text'] + text, carry['bm'] + bm, fixed or carry['fixed']
        if joined:
            carry = {'text': text, 'bm': bm, 'fixed': fixed}; continue
        carry = None
        out.append({'i': ci, 'text': text, 'bm': bm, 'fixed': fixed})
    return out


def _map(a, b):
    """Index of a -> index of b where the two lists read the same (equal stretches only)."""
    out = {}
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1): out[i1 + k] = j1 + k
    return out


def _ops(a, b):
    return [o for o in SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if o[0] != 'equal']


def _pairs(old, new):
    """Pair old and new paragraphs of one changed stretch: in order, by likeness (as gdoc_client.tracked does)."""
    if len(old) == len(new): return [(k, k) for k in range(len(old))]
    out, o = [], 0
    for n, text in enumerate(new):
        best, score = None, 0.4
        for k in range(o, len(old)):
            r = SequenceMatcher(None, old[k], text, autojunk=False).ratio()
            if r > score: best, score = k, r
        if best is None: out.append((None, n)); continue
        out += [(k, None) for k in range(o, best)]
        out.append((best, n)); o = best + 1
    out += [(k, None) for k in range(o, len(old))]
    return out


def _segments(old, new):
    """Phrase-sized changes of one paragraph (tiny same islands between two changes join them)."""
    ops = [list(o) for o in SequenceMatcher(None, old, new, autojunk=False).get_opcodes()]
    merged = []
    for op in ops:
        if merged and op[0] == 'equal' and op[2] - op[1] < 3 and merged[-1][0] != 'equal' and op is not ops[-1]:
            op = ['replace', *op[1:]]
        if merged and op[0] != 'equal' and merged[-1][0] != 'equal':
            merged[-1] = ['replace', merged[-1][1], op[2], merged[-1][3], op[4]]
        else: merged.append(op)
    return [(i1, i2, j1, j2) for tag, i1, i2, j1, j2 in merged if tag != 'equal']


def client_suggestions(P, C, W, W_raw, now=''):
    """What the customer changed (P -> C) as suggestions on the working doc: [(suggestion, the copy's texts it holds)].
    ``W_raw``: the working doc's paragraphs with every character (what the screen's suggestions are found in)."""
    import uuid
    mk = lambda **kw: {'id': M.OWNER + uuid.uuid4().hex[:12], 'bm': '', 'at': now, 'by': 'client', **kw}
    W_text = [w['text'] for w in W]
    p_to_w = _map(P, W_text)
    owner_ops = _ops(P, W_text)
    def owners_version(k):
        """The working paragraph the owner made of P[k] (both changed it), or None."""
        for _, a1, a2, b1, b2 in owner_ops:
            if a1 <= k < a2:
                for po, wn in _pairs(P[a1:a2], W_text[b1:b2]):
                    if po == k - a1: return None if wn is None else b1 + wn
        return None
    out = []
    for tag, i1, i2, k1, k2 in _ops(P, C):
        old, new = P[i1:i2], C[k1:k2]
        if any(TABLE in t or PICTURE in t for t in old + new): continue
        held = [t for t in new]
        prev_w = None
        for back in range(i1 - 1, -1, -1):
            if back in p_to_w: prev_w = p_to_w[back]; break
        for po, cn in _pairs(old, new):
            w = p_to_w.get(i1 + po) if po is not None else None
            if po is not None and w is None:
                # The owner changed this paragraph too: the customer's version as a change of the whole of it.
                w = owners_version(i1 + po)
                if w is None: continue
            if po is None:
                # A paragraph the customer added: its words at the end of the paragraph before it.
                if prev_w is None: continue
                raw = W_raw[prev_w]
                out.append((mk(para=W[prev_w]['i'], pre=raw[-M.CONTEXT:], post='', **{'del': '', 'ins': new[cn]}), held))
                continue
            prev_w = w
            raw = W_raw[w]
            if cn is None:
                out.append((mk(para=W[w]['i'], pre='', post='', **{'del': raw, 'ins': ''}), held)); continue
            o, n = old[po], new[cn]
            if raw != o:
                out.append((mk(para=W[w]['i'], pre='', post='', **{'del': raw, 'ins': n}), held)); continue
            for a1, a2, b1, b2 in _segments(o, n):
                out.append((mk(para=W[w]['i'], pre=o[:a1][-M.CONTEXT:], post=o[a2:][:M.CONTEXT],
                               **{'del': o[a1:a2], 'ins': n[b1:b2]}), held))
    return out


def copy_requests(copy_doc, P, C_paras, W, held=()):
    """Docs API requests that write the owner's changes (P -> W) into the copy, the last first. Stretches the
    customer changed (P -> C), ones holding a standing customer suggestion (``held`` texts) and tables / pictures
    are left. Returns (requests, written stretches, left stretches)."""
    C = [c['text'] for c in C_paras]
    p_to_c = _map(P, C)
    W_text = [w['text'] for w in W]
    reqs, done, left = [], 0, 0
    held = set(held)
    for tag, i1, i2, j1, j2 in reversed(_ops(P, W_text)):
        new = W[j1:j2]
        if any(w['fixed'] for w in new) or any(P[k] in held for k in range(i1, i2)):
            left += 1; continue
        if i2 > i1:
            cs = [p_to_c.get(k) for k in range(i1, i2)]
            if None in cs or cs != list(range(cs[0], cs[0] + len(cs))): left += 1; continue
            span = [C_paras[k] for k in cs]
            if any(c['fixed'] for c in span): left += 1; continue
            if new:
                before, after = span, new
            else:
                # Taking paragraphs out: together with the paragraph before (or after) them, which stays.
                nb = cs[0] - 1 if cs[0] > 0 else cs[-1] + 1
                if not 0 <= nb < len(C_paras) or C_paras[nb]['fixed']: left += 1; continue
                keep = C_paras[nb]
                before = [keep] + span if nb < cs[0] else span + [keep]
                after = [{'text': keep['text'], 'bm': keep['bm']}]
        else:
            # New paragraphs: after the paragraph before them, or before the one after them (whichever reads the same).
            at = p_to_c.get(i1 - 1) if i1 > 0 else None
            if at is not None and not C_paras[at]['fixed']:
                before = [C_paras[at]]; after = [C_paras[at]] + new
            else:
                at = p_to_c.get(i1) if i1 < len(P) else None
                if at is None or C_paras[at]['fixed']: left += 1; continue
                before = [C_paras[at]]; after = new + [C_paras[at]]
        got = S._para_span(copy_doc, before[0]['i'], before[-1]['i'])
        if got is None: left += 1; continue
        a, pos, abm, locked = got
        if any(locked): left += 1; continue          # the customer's own suggestion is in there
        b = '\n'.join(x['text'] for x in after)
        bbm = '0'.join(x['bm'][:len(x['text'])].ljust(len(x['text']), '0') for x in after)
        if a == b: continue
        reqs += S.replace_requests(pos, a, b, abm, bbm)
        done += 1
    return reqs, done, left


def _meta_path(client_id):
    return E.ROOT / 'client' / client_id / 'meta.json'


def _save_meta(meta):
    path = _meta_path(meta['client'])
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    tmp.replace(path)


def sync(work_id):
    """Bring the copy in step with the working doc now. Returns what was done."""
    import fcntl
    meta = _copy_of(work_id)
    if not meta: return {'copy': False}
    lock_path = _meta_path(meta['client']).with_suffix('.lock')
    with open(lock_path, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        meta = _copy_of(work_id)
        for attempt in range(4):
            try: return _sync_once(work_id, meta)
            except S.Stale:
                if attempt == 3: raise
                _time.sleep(1 + attempt)


def _sync_once(work_id, meta):
    client = meta['client']
    work_doc = S.fetch(work_id)
    copy_doc = S.fetch(client)
    W = paragraphs(work_doc)
    W_raw = [p['text'] for p in paragraphs(work_doc, confirmed=False)]
    if len(W_raw) != len(W): W_raw = [w['text'] for w in W]   # a suggested paragraph break: compare confirmed text
    C_paras = paragraphs(copy_doc, confirmed=False)
    C = [c['text'] for c in C_paras]
    P = meta.get('synced')
    now = _time.strftime('%Y-%m-%dT%H:%M:%S%z')
    result = {'copy': True, 'client': client, 'written': 0, 'left': 0, 'from_client': 0}
    if P is None:
        P = C               # first time: the copy as it is is what was given
    # What the customer did: into the working doc as suggestions (once; afterwards P holds it).
    standing = {s['id'] for s in M.load(S.OWNER_SUGS, work_id)}
    held = [h for h in meta.get('held') or [] if h.get('id') in standing]
    if C != P:
        found = client_suggestions(P, C, W, W_raw, now)
        if found:
            with S._owner_lock:
                M.save(S.OWNER_SUGS, work_id, M.load(S.OWNER_SUGS, work_id) + [s for s, _ in found])
            for s, texts in found: held.append({'id': s['id'], 'texts': texts})
            result['from_client'] = len(found)
    held_texts = {t for h in held for t in h['texts']}
    reqs, done, left = copy_requests(copy_doc, P, C_paras, W, held_texts)
    if reqs:
        S._docs('POST', f'{client}:batchUpdate', copy_doc['_account'],
                body={'requests': reqs, 'writeControl': {'requiredRevisionId': copy_doc['revisionId']}})
        copy_doc = S.fetch(client)
    result.update(written=done, left=left)
    meta = {**meta, 'synced': [c['text'] for c in paragraphs(copy_doc, confirmed=False)], 'held': held,
            'synced_at': datetime_now() if (reqs or meta.get('synced') is None or result['from_client']) else meta.get('synced_at'),
            'checked_at': datetime_now(), 'sync_error': None}
    _save_meta(meta)
    return result


def datetime_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _run(work_id):
    _timers.pop(work_id, None)
    try:
        sync(work_id)
    except Exception as exc:
        import logging
        logging.exception('customer copy sync failed for %s', work_id)
        meta = _copy_of(work_id)
        if meta:
            meta['sync_error'] = str(exc)[:300]; meta['checked_at'] = datetime_now()
            try: _save_meta(meta)
            except OSError: pass


def poke(work_id, delay=SYNC_AFTER):
    """The working doc (or its copy) changed: write the copy after a few quiet seconds (each change waits again)."""
    if not work_id or not _copy_of(work_id): return False
    old = _timers.pop(work_id, None)
    if old: old.cancel()
    t = threading.Timer(delay, _run, [work_id]); t.daemon = True
    _timers[work_id] = t; t.start()
    return True


def work_of(file_id):
    """The working doc of a customer copy (or the doc itself when it has a copy), or None."""
    for meta_path in (E.ROOT / 'client').glob('*/meta.json'):
        try: meta = json.loads(meta_path.read_text())
        except (OSError, ValueError): continue
        if file_id in (meta.get('client'), meta.get('work')): return meta.get('work')
    return None


def changed(file_ids):
    """Drive says these docs changed (gdoc_events' change feed): copies and working docs with a copy follow."""
    for fid in set(file_ids or ()):
        work = work_of(fid)
        if work: poke(work)


def maybe_check(work_id):
    """The screen is open on this doc (its polling): look at the copy now and then for what the customer did."""
    now = _time.time()
    if now - _last_check.get(work_id, 0) < CHECK_EVERY: return
    _last_check[work_id] = now
    if work_id not in _timers: poke(work_id, 0.5)
