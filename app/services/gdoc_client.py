"""The customer's copy of a working Google Doc.

The working doc holds the owner's comments and suggestions and is never shared
with the customer. The customer gets one fixed doc. Each delivery replaces its
content with the confirmed text of the working doc, and everything that changed
since the previous delivery is written as Word tracked changes, which Google
imports as suggestions. Same link every time, no owner comments, and the
customer sees what changed exactly like suggestion mode.
"""
import copy
from datetime import datetime, timezone
from difflib import SequenceMatcher
import io
import json
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree as ET

from app.services import gdoc_events as E

NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
W = '{%s}' % NS
DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
GDOC = 'application/vnd.google-apps.document'
XML_SPACE = '{http://www.w3.org/XML/1998/namespace}space'
COMMENT_PARTS = ('word/comments.xml', 'word/commentsExtended.xml', 'word/commentsIds.xml',
                 'word/commentsExtensible.xml', 'word/people.xml')


def _register_namespaces(xml):
    for prefix, uri in re.findall(rb'xmlns:([A-Za-z0-9]+)="([^"]+)"', xml):
        try: ET.register_namespace(prefix.decode(), uri.decode())
        except ValueError: pass


def _read(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    parts = {n: z.read(n) for n in z.namelist()}
    _register_namespaces(parts['word/document.xml'])
    return parts, ET.fromstring(parts['word/document.xml'])


def _write(parts, root):
    parts = dict(parts)
    parts['word/document.xml'] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, value in parts.items(): z.writestr(name, value)
    return out.getvalue()


def _parents(root):
    return {child: parent for parent in root.iter() for child in parent}


def paragraph_text(p):
    return ''.join(t.text or '' for t in p.iter(W+'t'))


def paragraphs(root):
    body = root.find(W+'body')
    return list(body.iter(W+'p')) if body is not None else []


def pending_suggestions(data):
    _, root = _read(data)
    return sum(1 for tag in ('ins', 'del', 'moveFrom', 'moveTo') for _ in root.iter(W+tag))


def clean(data, accept=False):
    """Confirmed text only: suggestions rejected in the copy, comments removed.
    With accept, every suggestion is applied instead (the working doc itself is untouched)."""
    parts, root = _read(data)
    drop, keep = (('del', 'moveFrom'), ('ins', 'moveTo')) if accept else (('ins', 'moveTo'), ('del', 'moveFrom'))
    split = [p for p in paragraphs(root) if p.find(W+'pPr/'+W+'rPr/'+W+drop[0]) is not None]
    parent = _parents(root)
    for tag in drop:
        for el in list(root.iter(W+tag)):
            holder = parent.get(el)
            if holder is None: continue
            holder.remove(el)  # in rPr this is the paragraph mark, handled with split below
    parent = _parents(root)
    for tag in keep:
        for el in list(root.iter(W+tag)):
            holder = parent.get(el)
            if holder is None: continue
            if holder.tag == W+'rPr':
                holder.remove(el); continue
            at = list(holder).index(el)
            holder.remove(el)
            for i, child in enumerate(list(el)): holder.insert(at+i, child)
    for t in list(root.iter(W+'delText')):
        t.tag = W+'t'
    # A paragraph whose break goes away (suggested insertion rejected, or suggested
    # deletion accepted) joins the next one.
    parent = _parents(root)
    for p in split:
        holder = parent.get(p)
        if holder is None: continue
        siblings = list(holder); at = siblings.index(p)
        following = next((x for x in siblings[at+1:] if x.tag == W+'p'), None)
        content = [c for c in p if c.tag != W+'pPr']
        if content and following is not None:
            start = 1 if following.find(W+'pPr') is not None else 0
            for i, c in enumerate(content): following.insert(start+i, c)
        if not content or following is not None: holder.remove(p)
    parent = _parents(root)
    for tag, prop in (('rPrChange', 'rPr'), ('pPrChange', 'pPr')):
        for change in list(root.iter(W+tag)):
            holder = parent.get(change)
            old = change.find(W+prop)
            grand = parent.get(holder)
            if grand is None: continue
            if old is None or accept:
                holder.remove(change); continue
            replacement = copy.deepcopy(old)
            if prop == 'pPr':
                mark = holder.find(W+'rPr')  # paragraph mark properties stay
                if mark is not None and replacement.find(W+'rPr') is None: replacement.append(copy.deepcopy(mark))
            at = list(grand).index(holder)
            grand.remove(holder); grand.insert(at, replacement)
    parent = _parents(root)
    for tag in ('commentRangeStart', 'commentRangeEnd'):
        for el in list(root.iter(W+tag)): parent[el].remove(el)
    parent = _parents(root)
    for ref in list(root.iter(W+'commentReference')):
        run = parent[ref]
        holder = parent.get(run)
        if holder is not None and all(c.tag in (W+'rPr', W+'commentReference') for c in run): holder.remove(run)
        else: run.remove(ref)
    for name in COMMENT_PARTS: parts.pop(name, None)
    rels = parts.get('word/_rels/document.xml.rels')
    if rels:
        parts['word/_rels/document.xml.rels'] = re.sub(rb'<Relationship [^>]*Target="(?:comments|commentsExtended|commentsIds|commentsExtensible|people)\.xml"[^>]*/>', b'', rels)
    types = parts.get('[Content_Types].xml')
    if types:
        parts['[Content_Types].xml'] = re.sub(rb'<Override [^>]*PartName="/word/(?:comments|commentsExtended|commentsIds|commentsExtensible|people)\.xml"[^>]*/>', b'', types)
    return _write(parts, root)


INTERNAL_HEADING = '◎前提と狙い'


def drop_internal(data):
    """The customer never sees the working doc's own notes: the ◎前提と狙い section
    (from that heading to the next ◎ heading) stays in the working doc only."""
    parts, root = _read(data)
    body = root.find(W+'body')
    if body is None: return data
    dropping, gone = False, []
    for el in list(body):
        if el.tag == W+'p':
            text = paragraph_text(el).strip()
            if text.startswith(INTERNAL_HEADING): dropping = True
            elif text.startswith('◎'): dropping = False
        if dropping and el.tag != W+'sectPr': gone.append(el)
    if not gone: return data
    for el in gone: body.remove(el)
    return _write(parts, root)


def texts(data, view='after'):
    """Body paragraph texts with every suggestion applied (after) or rejected (before)."""
    if view == 'before':
        return texts(clean(data), 'after')
    _, root = _read(data)
    result = []
    for p in paragraphs(root):
        out = []
        def walk(node, inserted=False, deleted=False):
            inserted = inserted or node.tag in (W+'ins', W+'moveTo')
            deleted = deleted or node.tag in (W+'del', W+'moveFrom')
            if node.tag in (W+'t', W+'delText') and not (inserted if view == 'before' else deleted):
                out.append(node.text or '')
            for child in node: walk(child, inserted, deleted)
        walk(p)
        mark = p.find(W+'pPr/'+W+'rPr')
        gone = mark is not None and mark.find(W+('ins' if view == 'before' else 'del')) is not None
        if gone and not ''.join(out): continue  # the paragraph itself is the suggestion
        result.append(''.join(out))
    return result


def _segments(old, new):
    """Phrase-level edits of one paragraph. Tiny unchanged islands between two edits
    are folded into the edit, so the customer reads 「Aを→Bに」 instead of
    single-character fragments that mean nothing on their own."""
    ops = [list(o) for o in SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes()]
    merged = []
    for op in ops:
        if (merged and op[0] == 'equal' and op[2]-op[1] < 3 and merged[-1][0] != 'equal'
                and op is not ops[-1]):
            op = ['replace', *op[1:]]
        if merged and op[0] != 'equal' and merged[-1][0] != 'equal':
            merged[-1] = ['replace', merged[-1][1], op[2], merged[-1][3], op[4]]
        else:
            merged.append(op)
    same = sum(o[2]-o[1] for o in merged if o[0] == 'equal')
    if not old or not new or same < 0.4*max(len(old), len(new)):
        return [('del', old, 0), ('ins', new, 0)] if old else [('ins', new, 0)]
    result = []
    for tag, i, j, k, l in merged:
        if tag == 'equal': result.append(('eq', new[k:l], k))
        else:
            if j > i: result.append(('del', old[i:j], k))
            if l > k: result.append(('ins', new[k:l], k))
    return result


class _Marks:
    def __init__(self, author, date):
        self.author, self.date, self.n = author, date, 9000

    def wrap(self, kind, child):
        self.n += 1
        el = ET.Element(W+kind, {W+'id': str(self.n), W+'author': self.author, W+'date': self.date})
        el.append(child)
        return el

    def mark(self, kind):
        self.n += 1
        return ET.Element(W+kind, {W+'id': str(self.n), W+'author': self.author, W+'date': self.date})


def _run(rpr, value, deleted=False):
    run = ET.Element(W+'r')
    if rpr is not None: run.append(copy.deepcopy(rpr))
    t = ET.SubElement(run, W+('delText' if deleted else 't'))
    t.text = value; t.set(XML_SPACE, 'preserve')
    return run


def _mark_paragraph(p, kind, marks):
    ppr = p.find(W+'pPr')
    if ppr is None:
        ppr = ET.Element(W+'pPr'); p.insert(0, ppr)
    rpr = ppr.find(W+'rPr')
    if rpr is None: rpr = ET.SubElement(ppr, W+'rPr')
    rpr.append(marks.mark(kind))


def _rewrite(p, old, marks):
    """Rewrite the runs of a changed paragraph with tracked insertions and deletions,
    keeping each run's formatting."""
    segs = _segments(old, paragraph_text(p))
    parent = _parents(p)
    runs = [r for r in p.iter(W+'r') if paragraph_text(r)]
    if not runs:
        for kind, value, _ in segs:
            if kind == 'del': p.append(marks.wrap('del', _run(None, value, True)))
        return
    out = {id(r): [] for r in runs}
    ri, offset = 0, 0
    for kind, value, _ in segs:
        if kind == 'del':
            r = runs[min(ri, len(runs)-1)]
            out[id(r)].append(marks.wrap('del', _run(r.find(W+'rPr'), value, True)))
            continue
        while value:
            r = runs[ri]; text = paragraph_text(r)
            take = min(len(text)-offset, len(value))
            piece = _run(r.find(W+'rPr'), text[offset:offset+take])
            out[id(r)].append(marks.wrap('ins', piece) if kind == 'ins' else piece)
            offset += take; value = value[take:]
            if offset == len(text): ri, offset = ri+1, 0
    for r in runs:
        made = out[id(r)]
        extras = [c for c in r if c.tag not in (W+'rPr', W+'t')]
        if extras:
            last = next((m for m in reversed(made) if m.tag in (W+'r', W+'ins')), None)
            target = last if last is None or last.tag == W+'r' else last[0]
            if target is not None:
                for extra in extras: target.append(extra)
        holder = parent[r]; at = list(holder).index(r)
        holder.remove(r)
        for i, el in enumerate(made): holder.insert(at+i, el)


def tracked(base_texts, new_clean, author='株式会社パイナ', when=None):
    """The new confirmed DOCX with every change since base_texts as tracked changes."""
    when = when or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    marks = _Marks(author, when)
    parts, root = _read(new_clean)
    paras = paragraphs(root)
    parent = _parents(root)
    new_texts = [paragraph_text(p) for p in paras]
    changed = 0
    def deleted_paragraph(value, before):
        holder = parent[before] if before is not None else root.find(W+'body')
        p = ET.Element(W+'p')
        _mark_paragraph(p, 'del', marks)
        if value: p.append(marks.wrap('del', _run(None, value, True)))
        if before is not None: holder.insert(list(holder).index(before), p)
        else:
            sect = holder.find(W+'sectPr')
            holder.insert(list(holder).index(sect) if sect is not None else len(holder), p)
    for tag, i, j, k, l in SequenceMatcher(a=base_texts, b=new_texts, autojunk=False).get_opcodes():
        if tag == 'equal': continue
        changed += 1
        old, new = base_texts[i:j], paras[k:l]
        # Pair each new paragraph with the most similar later old one, in order;
        # position alone pairs unrelated paragraphs when counts differ.
        o = 0
        for p in new:
            text = paragraph_text(p)
            best, score = None, 0.4
            for n in range(o, len(old)):
                ratio = SequenceMatcher(a=old[n], b=text, autojunk=False).ratio()
                if ratio > score: best, score = n, ratio
            if best is None:
                for r in [r for r in p.iter(W+'r')]:
                    holder = _parents(p).get(r)
                    if holder is None or holder.tag in (W+'ins', W+'del'): continue
                    at = list(holder).index(r); holder.remove(r); holder.insert(at, marks.wrap('ins', r))
                _mark_paragraph(p, 'ins', marks)
                continue
            for value in old[o:best]: deleted_paragraph(value, p)
            _rewrite(p, old[best], marks)
            o = best+1
        anchor = paras[l] if l < len(paras) else None
        for value in old[o:]: deleted_paragraph(value, anchor)
    return _write(parts, root), changed


def _norm(values):
    return [v.strip() for v in values if v.strip()]


def _state_dir(client_id):
    folder = E.ROOT/'client'/client_id
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder


def _upload(account, data, file_id=None, name=None):
    from app.services.gdoc_drive import request
    import httpx
    from app.services import gdoc_drive as G
    request(account, 'GET', 'about', params={'fields': 'user'})
    token = G._tokens[account][0]
    headers = {'Authorization': 'Bearer '+token}
    with httpx.Client(timeout=120, trust_env=False) as client:
        if file_id:
            response = client.patch(f'https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media&fields=id,name,version',
                                    headers={**headers, 'Content-Type': DOCX}, content=data)
        else:
            files = {'metadata': (None, json.dumps({'name': name, 'mimeType': GDOC}), 'application/json'),
                     'file': ('copy.docx', data, DOCX)}
            response = client.post('https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,version',
                                   headers=headers, files=files)
        response.raise_for_status()
        return response.json()


def status(account, client_id):
    """What the customer did since the last delivery: edits, rejected changes, comments."""
    from app.services.gdoc_drive import export_docx, comments
    folder = _state_dir(client_id)
    meta = json.loads((folder/'meta.json').read_text())
    current = export_docx(account, client_id)
    after = _norm(texts(current, 'after'))
    published = _norm(meta['published_after'])
    edits = [] if after == published else [
        {'operation': tag, 'published': published[i:j], 'now': after[k:l]}
        for tag, i, j, k, l in SequenceMatcher(a=published, b=after, autojunk=False).get_opcodes() if tag != 'equal']
    from app.services.script_learning import parse_docx
    foreign = [r for r in parse_docx(current)['revisions'] if r['author_label'] != meta['author'] and r['kind'] in ('ins', 'del')]
    notes = [{'id': t['id'], 'author': t.get('author', {}).get('displayName'), 'content': t.get('content'),
              'quote': (t.get('quotedFileContent') or {}).get('value'),
              'replies': [r.get('content') for r in t.get('replies', [])]}
             for t in comments(account, client_id) if not t.get('deleted') and not t.get('resolved')]
    return {'client': client_id, 'customer_edits': edits, 'customer_suggestions': foreign, 'open_comments': notes,
            'last_delivery': meta.get('delivered_at')}


def deliver(account, work_id, client_id=None, name=None, author='株式会社パイナ', allow_pending=False, force=False, dry_run=False,
            with_pending=False):
    """with_pending sends the text as if every suggestion in the working doc were accepted,
    while the working doc keeps them as suggestions (the owner reviews them later)."""
    from app.services.gdoc_drive import export_docx
    work = export_docx(account, work_id)
    pending = pending_suggestions(work)
    if pending and not (allow_pending or with_pending):
        raise ValueError(f'The working doc still has {pending} unresolved suggestion marks; accept or reject them, '
                         'pass with_pending to send them as accepted, or allow_pending to send only the confirmed text')
    fresh = clean(work, accept=with_pending)
    new_texts = texts(fresh, 'after')
    if with_pending and ''.join(_norm(new_texts)) != ''.join(_norm(texts(work, 'after'))):  # joined: texts keeps deleted breaks
        raise RuntimeError('Applying the working doc suggestions did not give the suggested text')
    fresh = drop_internal(fresh)
    new_texts = texts(fresh, 'after')
    if client_id:
        folder = _state_dir(client_id)
        meta = json.loads((folder/'meta.json').read_text())
        seen = status(account, client_id)
        if not force and (seen['customer_edits'] or seen['customer_suggestions'] or seen['open_comments']):
            raise ValueError('The customer changed or commented on the copy; bring that into the working doc first: '
                             + json.dumps(seen, ensure_ascii=False)[:3000])
        base = meta['published_after']
        output, changed = tracked(base, fresh, author)
    else:
        output, changed, base = fresh, 0, []
    if dry_run:
        return {'changed_blocks': changed, 'pending_in_work': pending, 'bytes': len(output), 'output': output}
    result = _upload(account, output, client_id, name)
    client_id = result['id']
    folder = _state_dir(client_id)
    check = export_docx(account, client_id)
    got_after, got_before = _norm(texts(check, 'after')), _norm(texts(check, 'before'))
    ok = got_after == _norm(new_texts) and (not base or got_before == _norm(base))
    (folder/'delivered.docx').write_bytes(output)
    meta = {'work': work_id, 'client': client_id, 'author': author, 'published_after': new_texts,
            'delivered_at': datetime.now(timezone.utc).isoformat(), 'verified': ok}
    (folder/'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    if not ok:
        raise RuntimeError('Uploaded copy does not read back as expected; see '+str(folder))
    return {'client': client_id, 'url': f'https://docs.google.com/document/d/{client_id}/edit',
            'changed_blocks': changed, 'pending_in_work': pending, 'verified': ok}


def adopt(account, work_id, client_id, author='株式会社パイナ'):
    """Take over a customer copy made before this tool: what the customer sees now
    is the base, so the next delivery shows every change from there."""
    from app.services.gdoc_drive import export_docx, comments
    current = export_docx(account, client_id)
    if pending_suggestions(current) or [t for t in comments(account, client_id) if not t.get('deleted') and not t.get('resolved')]:
        raise ValueError('The copy has suggestions or open comments; bring them into the working doc first')
    folder = _state_dir(client_id)
    meta = {'work': work_id, 'client': client_id, 'author': author, 'published_after': texts(current, 'after'),
            'delivered_at': None, 'adopted_at': datetime.now(timezone.utc).isoformat(), 'verified': True}
    (folder/'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    return {'client': client_id, 'paragraphs': len(meta['published_after'])}

