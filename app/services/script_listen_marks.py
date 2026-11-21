"""Suggestions on the script listening screen, as characters (2026-11-20).

Owner 11/20:「提案モードで入れられている文字を変更できない…普通に編集できるようにしてほしい」「僕の方で提案モードで何か
書き込んだりするということができないので、それもできるようにしたい」.

Two things live here, both pure (no Google calls), so they can be tested:

- The owner's own suggestions. The Docs API cannot write suggestions (it has no suggestion mode), so what the owner
  writes in suggestion mode on the screen is kept by the screen (STATE/owner_suggestions.json) and laid over the doc
  when it is read: the words it takes out are marked as a suggested deletion, the words it adds are put in as a
  suggested insertion that has no place in the doc yet (``_virtual``). Each one is found again by its words and the
  words around it, so changes elsewhere in the doc do not lose it. Their ids start with ``o-``.
- Typing over a suggestion. The screen sends「these paragraphs read X, now read Y」. Every character of X is known as
  plain, a doc suggestion (Dan's), or the owner's. Changing the words of a suggestion changes the suggestion and it
  stays one, in either mode (11/21 本人「承認や却下せずそのまま書き換えると、勝手に承認されて文字が本文に入ってしまう」):
  only 承認 / 却下 decide it. Dan's suggestion is first made the owner's with the same words (``Adopt``; the doc's
  suggestion is taken back and the screen keeps it, with what Dan had suggested for the learning).
"""
from __future__ import annotations

import copy
import json
import uuid
from difflib import SequenceMatcher

CONTEXT = 24
OWNER = 'o-'


def u16(ch):
    return len(ch.encode('utf-16-le')) // 2


def is_owner(sid):
    return bool(sid) and str(sid).startswith(OWNER)


class Refused(Exception):
    """The change cannot be made as asked (the message is for the owner)."""


class Settle(Exception):
    """Dan's suggestions must be decided in the doc first: {sid: accept}."""
    def __init__(self, decisions):
        super().__init__('settle')
        self.decisions = decisions


class Adopt(Exception):
    """The owner is typing into Dan's suggestions (``sids``): they become the owner's own suggestions first, with
    the same words, so the change keeps them suggestions (11/21 本人「提案モードで置き換えや削除や追加されてる文章を承認や
    却下せずそのまま書き換えると、勝手に承認されて文字が本文に入ってしまう」「提案状態で書き換える意図はそれが良い文章だという
    データを貯めるため」)."""
    def __init__(self, sids):
        super().__init__('adopt')
        self.sids = set(sids)


# ---------------------------------------------------------------- laying the owner's suggestions over the doc

def _raw(paragraph):
    """The paragraph's characters (text runs only, without the closing newline), as the screen shows them."""
    out = ''.join(e['textRun']['content'] for e in paragraph.get('elements', []) if e.get('textRun'))
    return out.rstrip('\n')


def _find(raw, sug, taken):
    """Where ``sug`` sits in ``raw``: the offset of its first struck character (or of where it adds), or None. Its
    words with the words around it first, then with fewer of them. Nothing before / after it = the paragraph's
    start / end."""
    pre, dele, post = sug.get('pre') or '', sug.get('del') or '', sug.get('post') or ''
    tries = [(pre, post)]
    if len(pre) > 8 or len(post) > 8: tries.append((pre[-8:], post[:8]))
    if len(dele) >= 2: tries += [('', post[:8]), (pre[-8:], '')]
    for a, b in tries:
        pat = a + dele + b
        i = raw.find(pat) if pat else (0 if raw == '' else -1)
        while i >= 0:
            s = i + len(a)
            e = s + len(dele)
            ok = (pre or s == 0) and (post or e == len(raw))
            if ok and not any(x < e and s < y for x, y in taken): return s
            i = raw.find(pat, i + 1) if pat else -1
    return None


def overlay(doc, sugs):
    """A copy of ``doc`` with the owner's suggestions laid in, and where each one was placed ({sid: paragraph}).
    Suggestions whose words are no longer in the doc are left out (and come back if the words do)."""
    sugs = [s for s in (sugs or []) if s.get('id') and (s.get('del') or s.get('ins'))]
    content = doc.get('body', {}).get('content', [])
    if not sugs or not content: return doc, {}
    view = dict(doc)
    view['body'] = dict(doc['body'])
    view['body']['content'] = list(content)
    raws = {pi: _raw(el['paragraph']) for pi, el in enumerate(content) if el.get('paragraph')}
    placed, marks = {}, {}
    def under(pi, s):
        # Words that make a whole paragraph (nothing around them) are found by the paragraph above with words in it,
        # so they do not land in another empty paragraph when paragraphs come or go before them.
        above, gap = s.get('above'), s.get('gap') or 0
        if above is None or s.get('pre') or s.get('post') or s.get('del'): return False
        k = pi - 1 - gap
        return (k in raws and raws[k].endswith(above) and raws[k] != ''
                and all(raws.get(q, None) == '' for q in range(k + 1, pi)))
    for s in sorted(sugs, key=lambda x: x.get('at') or ''):
        hint = s.get('para') if isinstance(s.get('para'), int) else 0
        for pi in sorted(raws, key=lambda p: (not under(p, s), abs(p - hint), p)):
            taken = [(m[0], m[0] + len(m[1].get('del') or '')) for m in marks.get(pi, [])]
            at = _find(raws[pi], s, taken)
            if at is None: continue
            marks.setdefault(pi, []).append((at, s))
            placed[s['id']] = pi
            break
    for pi, ms in marks.items():
        el = dict(content[pi])
        el['paragraph'] = dict(el['paragraph'])
        el['paragraph']['elements'] = _marked(el['paragraph'].get('elements', []), ms)
        view['body']['content'][pi] = el
    return view, placed


def _marked(elements, marks):
    """The paragraph's elements with the owner's suggestions marked: struck characters carry the suggestion's id as a
    suggested deletion, added words are new runs at the place they would go (``_virtual``: no room in the doc yet)."""
    items = []          # ('c', ch, idx, meta) or ('e', element)
    for e in elements:
        run = e.get('textRun')
        if not run:
            items.append(('e', e)); continue
        meta = {k: v for k, v in run.items() if k != 'content'}
        idx = e['startIndex']
        for ch in run['content']:
            items.append(('c', ch, idx, meta)); idx += u16(ch)
    # raw offset -> item position
    where, k = [], 0
    for i, it in enumerate(items):
        if it[0] == 'c': where.append(i)
    adds = {}
    for at, s in marks:
        sid, dele = s['id'], s.get('del') or ''
        for off in range(at, at + len(dele)):
            if off >= len(where): break
            i = where[off]
            _, ch, idx, meta = items[i]
            m = dict(meta)
            m['suggestedDeletionIds'] = list(meta.get('suggestedDeletionIds') or []) + [sid]
            items[i] = ('c', ch, idx, m)
        if s.get('ins'): adds[at + len(dele)] = s
    out_items = []
    off = 0
    for i, it in enumerate(items):
        if it[0] == 'c':
            if off in adds:
                out_items += _virtual(adds.pop(off), it[2], it[3])
            off += 1
        out_items.append(it)
    for s in adds.values():      # after the last character (a paragraph without its newline)
        last = next((x for x in reversed(items) if x[0] == 'c'), None)
        out_items += _virtual(s, (last[2] + u16(last[1])) if last else 0, last[3] if last else {})
    # Put runs back together.
    out, cur = [], None
    for it in out_items:
        if it[0] == 'e':
            cur = None; out.append(it[1]); continue
        _, ch, idx, meta = it
        virt = meta.get('_virtual')
        if cur and cur['_meta'] is meta and (virt or cur['_end'] == idx):
            cur['textRun']['content'] += ch
            if not virt: cur['_end'] = idx + u16(ch)
            continue
        cur = {'startIndex': idx, 'textRun': {**meta, 'content': ch}, '_meta': meta, '_end': idx if virt else idx + u16(ch)}
        out.append(cur)
    for e in out:
        if '_meta' in e:
            e['endIndex'] = e.pop('_end'); e.pop('_meta')
    return out


def _virtual(s, idx, near):
    style = dict((near or {}).get('textStyle') or {})
    meta = {'textStyle': style, 'suggestedInsertionIds': [s['id']], '_virtual': True}
    bm = s.get('bm') or ''
    out = []
    for k, ch in enumerate(s['ins']):
        bold = k < len(bm) and bm[k] == '1'
        m = meta if bool(style.get('bold')) == bold else {**meta, 'textStyle': {**style, 'bold': bold}}
        out.append(('c', ch, idx, m))
    # one meta object per run of the same boldness (runs are joined by identity)
    joined, last = [], None
    for c in out:
        if last and last[3]['textStyle'].get('bold') == c[3]['textStyle'].get('bold'): c = (c[0], c[1], c[2], last[3])
        joined.append(c); last = c
    return joined


# ---------------------------------------------------------------- characters of a stretch of paragraphs

def tokens(view, para_from, para_to, chars_of):
    """Paragraphs ``para_from``..``para_to`` as characters: dicts with ch, pos (doc index; for added words the place
    they go), b (bold), k ('p' plain, 'x' a doc suggestion, 'i' / 'd' the owner's added / struck words, 'n' the end of
    a paragraph) and sid. Also the doc index after the last character. None when one of them is not a paragraph."""
    content = view.get('body', {}).get('content', [])
    if not (0 <= para_from <= para_to < len(content)): return None
    out = []
    for pi in range(para_from, para_to + 1):
        p = content[pi].get('paragraph')
        if p is None: return None
        if pi > para_from:
            out.append({'ch': '\n', 'pos': content[pi - 1]['endIndex'] - 1, 'b': False, 'k': 'n', 'sid': None})
        for idx, ch, f in chars_of(p):
            ins, dele = f['ins'], f['del']
            own = next((x for x in (*ins, *dele) if is_owner(x)), None)
            other = next((x for x in (*ins, *dele) if not is_owner(x)), None)
            if other: k, sid = 'x', other
            elif own: k, sid = ('i' if own in ins else 'd'), own
            else: k, sid = 'p', None
            out.append({'ch': ch, 'pos': idx, 'b': bool(f['bold']), 'k': k, 'sid': sid,
                        'xk': ('i' if other in ins else 'd') if other else None})
    return out, content[para_to]['endIndex'] - 1


def text_of(toks):
    return ''.join(t['ch'] for t in toks)


def bmask_of(toks):
    return ''.join('1' if t['b'] else '0' for t in toks)


# ---------------------------------------------------------------- what a change means

def ops_for(old_toks, new):
    """How ``old_toks`` became ``new``, the way a person would say it: a change does not land on a suggestion's letter
    when the same letter next to it would do (``x`` + suggested 「ab」 + 「b」, one 「b」 taken out = the plain one), and
    one change does not break into pieces around a shared letter (「大事」→「とても大切」 is one change, not
    「とても」 + 「事」→「切」 around the 大 they share)."""
    old = text_of(old_toks)
    ops = [list(o) for o in SequenceMatcher(None, old, new, autojunk=False).get_opcodes()]
    locked = lambda i: 0 <= i < len(old_toks) and old_toks[i]['k'] in ('x', 'i', 'd')
    def bad(tag, i1, i2):
        if tag == 'delete': return sum(1 for i in range(i1, i2) if locked(i))
        if 0 < i1 < len(old_toks) and old_toks[i1 - 1]['sid'] and old_toks[i1 - 1]['sid'] == old_toks[i1]['sid']: return 1
        return 0
    for k, op in enumerate(ops):
        tag, i1, i2, j1, j2 = op
        if tag not in ('delete', 'insert') or not bad(tag, i1, i2): continue
        prev = ops[k - 1] if k and ops[k - 1][0] == 'equal' else None
        nxt = ops[k + 1] if k + 1 < len(ops) and ops[k + 1][0] == 'equal' else None
        best, score = 0, bad(tag, i1, i2)
        for d in range(1, 9):              # to the right
            if not nxt or nxt[2] - nxt[1] < d: break
            if (tag == 'delete' and old[i1 + d - 1] != old[i2 + d - 1]) or (tag == 'insert' and old[i1 + d - 1] != new[j1 + d - 1]): break
            b = bad(tag, i1 + d, i2 + d)
            if b < score: best, score = d, b
        for d in range(1, 9):              # to the left
            if not prev or prev[2] - prev[1] < d or score == 0: break
            if (tag == 'delete' and old[i1 - d] != old[i2 - d]) or (tag == 'insert' and old[i1 - d] != new[j2 - d]): break
            b = bad(tag, i1 - d, i2 - d)
            if b < score: best, score = -d, b
        if best:
            op[1] += best; op[2] += best; op[3] += best; op[4] += best
            if prev: prev[2] += best; prev[4] += best
            if nxt: nxt[1] += best; nxt[3] += best
    ops = [o for o in ops if o[2] > o[1] or o[4] > o[3]]
    # Join changes split by one or two shared letters (not across a paragraph end or a suggestion's letter).
    out = []
    for o in ops:
        if (o[0] != 'equal' and len(out) >= 2 and out[-1][0] == 'equal' and out[-2][0] != 'equal'
                and out[-1][2] - out[-1][1] <= 2 and '\n' not in old[out[-1][1]:out[-1][2]]
                and not any(locked(i) for i in range(out[-1][1], out[-1][2]))):
            gap = out.pop(); first = out.pop()
            out.append(['replace', first[1], o[2], first[3], o[4]])
            continue
        out.append(o)
    for o in out:
        if o[0] != 'equal': o[0] = 'replace' if o[2] > o[1] and o[4] > o[3] else 'delete' if o[2] > o[1] else 'insert'
    return [tuple(o) for o in out]


def _signals(old_toks, ops):
    """For every suggestion whose words the change touches: True = take it (accept), False = keep the old words."""
    sig = {}
    def put(sid, accept):
        if accept: sig[sid] = True
        else: sig.setdefault(sid, False)
    kinds = lambda t: t['xk'] if t['k'] == 'x' else t['k']
    for tag, i1, i2, j1, j2 in ops:
        if tag == 'equal': continue
        for t in old_toks[i1:i2]:
            if not t['sid']: continue
            # Changing the words it adds, or taking out struck words (they go anyway when taken): take it. Typing over
            # struck words: keep the old words, changed.
            put(t['sid'], kinds(t) == 'i' or tag == 'delete')
        if j2 > j1 and 0 < i1 < len(old_toks):
            a, b = old_toks[i1 - 1], old_toks[i1] if i1 < len(old_toks) else None
            if b is not None and a['sid'] and a['sid'] == b['sid']:
                put(a['sid'], kinds(a) == 'i')
            elif b is not None and a['k'] == b['k'] == 'x' and a['sid'] and b['sid']:
                # Between two of Dan's suggestions that sit together (one inside another, 11/21 「そして|2」): it is
                # inside his words all the same.
                put(a['sid'], kinds(a) == 'i'); put(b['sid'], kinds(b) == 'i')
    return sig


def plan(old_toks, new, new_bmask, mode, force=None):
    """The characters after the owner turned ``old_toks`` into ``new`` (with bold ``new_bmask``), in ``mode`` 'edit'
    (the doc changes) or 'suggest' (the change becomes the owner's suggestion). Returns (tokens, settled) where
    settled is {owner sid: accept} decided by this change. Raises Settle when Dan's suggestions must be decided in
    the doc first, Refused when the change cannot be made."""
    ops = ops_for(old_toks, new)
    force = force or {}
    sig = _signals(old_toks, ops)
    dans = {s for s in sig if not is_owner(s) and s not in force}
    if dans: raise Adopt(dans)
    dans_forced = {s: a for s, a in force.items() if not is_owner(s)}
    if dans_forced: raise Settle(dans_forced)
    # A suggestion is decided only by 承認 / 却下 (``force``). Typing into one, in either mode, changes the
    # suggestion: what that change does is written the way suggestion mode writes it (11/21 本人).
    settled = {s: a for s, a in force.items() if is_owner(s)}
    touched = {s for s in sig if s not in force}
    def into_suggestion(i1, i2):
        if any(t['sid'] in touched for t in old_toks[i1:i2]): return True
        if 0 < i1 < len(old_toks):
            a, b = old_toks[i1 - 1], old_toks[i1]
            return bool(a['sid']) and a['sid'] == b['sid'] and a['sid'] in touched
        return False
    nb = lambda j: j < len(new_bmask) and new_bmask[j] == '1'
    out = []
    for tag, i1, i2, j1, j2 in ops:
        op_mode = 'suggest' if tag != 'equal' and into_suggestion(i1, i2) else mode
        if tag == 'equal':
            for k in range(i2 - i1):
                t = dict(old_toks[i1 + k]); t['b'] = nb(j1 + k); t['src'] = i1 + k
                if t['sid'] in settled:
                    keep = (t['k'] == 'i') == settled[t['sid']]
                    if not keep: continue
                    t['k'], t['sid'] = ('new' if t['k'] == 'i' else 'p'), None
                out.append(t)
            continue
        for k, t in enumerate(old_toks[i1:i2]):
            if op_mode == 'edit' or t['k'] == 'i': continue
            if t['k'] == 'n':
                raise Refused('提案モードでは、段落をつなげることはできません。編集モードに切り替えてください。' if mode == 'suggest' else
                              '提案の文字と一緒に段落をつなげることはできません。提案を承認か却下してからつなげてください。')
            if t['k'] == 'x': raise Refused('ダンの提案の文字は、提案モードでは消せません。')
            t = dict(t); t['src'] = i1 + k
            if t['k'] == 'p': t['k'], t['sid'] = 'd', None
            out.append(t)
        for j in range(j1, j2):
            ch = new[j]
            if ch == '\n':
                if op_mode == 'suggest':
                    raise Refused('提案モードでは、段落を分けることはできません。編集モードに切り替えてください。' if mode == 'suggest' else
                                  '提案の文字の中では段落を分けられません。提案を承認か却下してから分けてください。')
                out.append({'ch': '\n', 'k': 'n', 'sid': None, 'b': False, 'pos': None}); continue
            out.append({'ch': ch, 'k': 'new' if op_mode == 'edit' else 'i', 'sid': None, 'b': nb(j), 'pos': None})
    return out, settled


def drop_settled(old_toks, new, new_bmask, decisions, new_dmask=''):
    """The change as it reads once ``decisions`` ({sid: accept}) are made in the doc: the words that go with them are
    taken out of both sides. Returns (old, old bold, new, new bold, new struck)."""
    old = text_of(old_toks)
    kind = lambda t: t['xk'] if t['k'] == 'x' else t['k']
    gone = lambda t: t['sid'] in decisions and (kind(t) == 'i') != decisions[t['sid']]
    o = [t for t in old_toks if not gone(t)]
    n, nb, nd = [], [], []
    for tag, i1, i2, j1, j2 in ops_for(old_toks, new):
        for j in range(j1, j2):
            if tag == 'equal' and gone(old_toks[i1 + j - j1]): continue
            n.append(new[j]); nb.append(new_bmask[j] if j < len(new_bmask) else '0')
            nd.append(new_dmask[j] if j < len(new_dmask) else '0')
    return text_of(o), bmask_of(o), ''.join(n), ''.join(nb), ''.join(nd)


def doc_change(old_toks, new_toks):
    """What the doc itself must become: (old text, positions, old bold, new text, new bold, doc-suggestion lock, ops).
    Only characters that are in the doc count (the owner's added words are not, its struck words are). The ops come
    from which character is which, not from comparing the two texts, so a doc suggestion next to the same letter is
    never taken for the changed one."""
    real = lambda t: t['k'] in ('p', 'x', 'd', 'n')
    a_idx = [i for i, t in enumerate(old_toks) if real(t)]
    where = {i: k for k, i in enumerate(a_idx)}
    a = [old_toks[i] for i in a_idx]
    b = [t for t in new_toks if real(t) or t['k'] == 'new']
    pairs = [(where[t['src']], j) for j, t in enumerate(b) if t.get('src') in where]
    ops, pa, pb = [], 0, 0
    for ia, jb in pairs + [(len(a), len(b))]:
        if ia > pa or jb > pb:
            tag = 'replace' if ia > pa and jb > pb else 'delete' if ia > pa else 'insert'
            ops.append((tag, pa, ia, pb, jb))
        if ia < len(a):
            if ops and ops[-1][0] == 'equal' and ops[-1][2] == ia: ops[-1] = ('equal', ops[-1][1], ia + 1, ops[-1][3], jb + 1)
            else: ops.append(('equal', ia, ia + 1, jb, jb + 1))
        pa, pb = ia + 1, jb + 1
    return (text_of(a), [t['pos'] for t in a], bmask_of(a), text_of(b), bmask_of(b), [t['k'] == 'x' for t in a], ops)


def regroup(new_toks, para_from, ids=None, now=''):
    """The owner's suggestions in these paragraphs after the change: each run of added / struck words is one
    suggestion, with the words around it to find it again. ``ids`` gives new ones their ids (tests)."""
    paras, cur = [], []
    for t in new_toks:
        if t['k'] == 'n': paras.append(cur); cur = []
        else: cur.append(t)
    paras.append(cur)
    out = []
    for k, toks in enumerate(paras):
        i = 0
        while i < len(toks):
            if toks[i]['k'] not in ('i', 'd'): i += 1; continue
            j = i
            while j < len(toks) and toks[j]['k'] in ('i', 'd'): j += 1
            run = toks[i:j]
            before = ''.join(t['ch'] for t in toks[:i] if t['k'] in ('p', 'x', 'd', 'new'))
            after = ''.join(t['ch'] for t in toks[j:] if t['k'] in ('p', 'x', 'd', 'new'))
            dele = ''.join(t['ch'] for t in run if t['k'] == 'd')
            ins = [t for t in run if t['k'] == 'i']
            insert, bm = ''.join(t['ch'] for t in ins), ''.join('1' if t['b'] else '0' for t in ins)
            # The same words struck and added again are no change.
            while dele and insert and dele[0] == insert[0]:
                before += dele[0]; dele, insert, bm = dele[1:], insert[1:], bm[1:]
            while dele and insert and dele[-1] == insert[-1]:
                after = dele[-1] + after; dele, insert, bm = dele[:-1], insert[:-1], bm[:-1]
            if dele or insert:
                sid = next((t['sid'] for t in run if t['sid']), None)
                if not sid: sid = next(ids) if ids else OWNER + uuid.uuid4().hex[:12]
                out.append({'id': sid, 'para': para_from + k, 'pre': before[-CONTEXT:], 'del': dele, 'ins': insert,
                            'bm': bm, 'post': after[:CONTEXT], 'at': now})
            i = j
    # one suggestion keeps one id
    seen, uniq = set(), []
    for s in out:
        if s['id'] in seen: s['id'] = next(ids) if ids else OWNER + uuid.uuid4().hex[:12]
        seen.add(s['id']); uniq.append(s)
    return uniq


def store_after(sugs, placed, para_from, para_to, delta, fresh):
    """The doc's list of owner suggestions after a change of paragraphs ``para_from``..``para_to`` (now ``delta`` more
    paragraphs): the ones that were there are replaced by ``fresh``, the later ones move with the paragraphs. Ones not
    found in the doc now are kept (their words may come back)."""
    out = []
    for s in sugs:
        p = placed.get(s['id'])
        if p is not None and para_from <= p <= para_to: continue
        if p is not None and p > para_to: s = {**s, 'para': p + delta}
        elif p is not None: s = {**s, 'para': p}
        out.append(s)
    return out + fresh


# ---------------------------------------------------------------- the doc changed while the owner typed

def rebase(base, theirs, ours, ours_bmask, theirs_bmask):
    """Put the owner's change (``base`` -> ``ours``) onto the doc as it is now (``base`` -> ``theirs``, e.g. Dan put in a
    suggestion meanwhile) when the two do not touch the same words. Returns (new text, new bold) or None."""
    if base.count('\n') != theirs.count('\n'): return None
    t_ops = [o for o in SequenceMatcher(None, base, theirs, autojunk=False).get_opcodes() if o[0] != 'equal']
    o_ops = [o for o in SequenceMatcher(None, base, ours, autojunk=False).get_opcodes() if o[0] != 'equal']
    for _, a1, a2, _, _ in t_ops:
        for _, b1, b2, _, _ in o_ops:
            if a1 <= b2 and b1 <= a2: return None       # touching or next to each other
    def m(i):
        d = 0
        for _, a1, a2, c1, c2 in t_ops:
            if a2 <= i: d += (c2 - c1) - (a2 - a1)
        return i + d
    text, bold = theirs, theirs_bmask
    for _, b1, b2, j1, j2 in reversed(o_ops):
        x, y = m(b1), m(b2)
        text = text[:x] + ours[j1:j2] + text[y:]
        bold = bold[:x] + ours_bmask[j1:j2] + bold[y:]
    return text, bold


def load(path, doc_id):
    try: return list((json.loads(path.read_text()) or {}).get(doc_id) or [])
    except Exception: return []


def save(path, doc_id, sugs):
    try: data = json.loads(path.read_text()) or {}
    except Exception: data = {}
    if sugs: data[doc_id] = sugs
    else: data.pop(doc_id, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(path)


def deep(doc):
    return copy.deepcopy(doc)
