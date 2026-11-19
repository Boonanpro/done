"""Listening to a talk script (2026-11-18, owner: 「聞いてチェックして、その場でテキストを編集したらその音声ですぐ再生できる
やつほしい。無言の変な間が無いようにテンポよく。倍速でも声の高さが変わらないように」).

The Google Doc is the source of truth. Each read goes to the Docs API, the script part (after 「◎台本」) is cut into
sentences, and each sentence is spoken by the local AivisSpeech engine (free, runs on the Mac mini; set up with
scripts/install_aivis_speech.py). A sentence's audio is cached by its text, so after an edit only that sentence is made
again. Silence at the head and tail of every clip is cut and a short fixed pause is put after it (longer at the end of
a paragraph and of a section), which is what makes the reading sound continuous. The player changes speed with the
browser's pitch-keeping playback, so nothing here depends on the speed.

Editing writes the smallest change into the doc (only the characters that differ), so bold and colour around it stay.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path

import httpx

ENGINE = os.environ.get('DAN_AIVIS_URL', 'http://127.0.0.1:10101')
STATE = Path.home() / '.dan' / 'script-listen'
CACHE = STATE / 'cache'
ACCOUNTS = ('shub6923',)
VOICES = [
    # Chosen 11/18 by making the same four script sentences with 11 voices (AivisSpeech 7, OpenAI 4): this one was judged
    # the most natural Japanese (9/10 twice), read every word right and scored NISQA 4.7. OpenAI's speech API retires
    # 2027-01-06 and Gemini's needs paid credit, so the free local engine is the default.
    {'id': 'aida-calm', 'name': '阿井田 茂（落ち着き）', 'speaker': '阿井田 茂', 'style': 'Calm'},
    {'id': 'aida', 'name': '阿井田 茂（ふつう）', 'speaker': '阿井田 茂', 'style': 'ノーマル'},
    {'id': 'shinjou', 'name': 'Shinjou Tomoharu', 'speaker': 'Shinjou Tomoharu', 'style': 'ノーマル'},
    {'id': 'm1', 'name': 'M1', 'speaker': 'M1', 'style': 'ノーマル'},
]
DEFAULT_VOICE = 'aida-calm'
# Pause put after a clip, in seconds at 1x (the player's speed shortens it with the voice).
GAPS = {'s': 0.16, 'p': 0.32, 'h': 0.65}
PAUSE_SCALE = 0.7          # pauses at 「、」 inside a sentence
RECIPE = 'v1'              # bump when the way a clip is made changes, so old clips are not reused

SKIP_HEADINGS = ('◎サムネ', '◎タイトル', '◎前提と狙い', '◎タイトルとサムネ')
SCRIPT_HEADING = '◎台本'
END = '。！？!?'
CLOSE = '」』）)】〉》"\'”’'


class ListenError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- Google Docs

def _token(account):
    from app.services import gdoc_drive as G
    G.request(account, 'GET', 'about', params={'fields': 'user'})
    return G._tokens[account][0]


def _docs(method, path, account, body=None, params=None):
    with httpx.Client(timeout=40, trust_env=False) as c:
        r = c.request(method, 'https://docs.googleapis.com/v1/documents/' + path,
                      headers={'Authorization': 'Bearer ' + _token(account)}, json=body, params=params)
    if r.status_code == 404 or r.status_code == 403:
        raise ListenError('このドキュメントを開けませんでした。ダンのGoogleアカウントに共有されているか確かめてください。', 404)
    if r.status_code == 400 and 'requiredRevisionId' in r.text:
        raise ListenError('ドキュメントがちょうど直されたので、読み直しました。', 409)
    r.raise_for_status()
    return r.json()


def fetch(doc_id):
    """The doc as the Docs API gives it, read with the first account that can open it."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,}', doc_id or ''):
        raise ListenError('ドキュメントのURLかIDが正しくありません。')
    last = None
    for account in ACCOUNTS:
        try:
            doc = _docs('GET', doc_id, account)
            doc['_account'] = account
            return doc
        except ListenError as exc:
            last = exc
    raise last


def doc_id_from(value):
    m = re.search(r'/document/d/([A-Za-z0-9_-]+)', value or '')
    return m.group(1) if m else (value or '').strip()


def _units16(ch):
    return len(ch.encode('utf-16-le')) // 2


def _is_blue(style):
    rgb = (((style or {}).get('foregroundColor') or {}).get('color') or {}).get('rgbColor')
    if not rgb: return False
    r, g, b = rgb.get('red', 0), rgb.get('green', 0), rgb.get('blue', 0)
    return b > 0.45 and b - max(r, g) > 0.2


def _chars(paragraph):
    """Every character of a paragraph with its place in the doc and what marks it carries."""
    out = []
    for el in paragraph.get('elements', []):
        run = el.get('textRun')
        if not run: continue
        idx = el['startIndex']
        style = run.get('textStyle') or {}
        # del / ins are the suggestion ids (a tuple, empty when none), so they still read as true / false.
        flags = {'del': tuple(run.get('suggestedDeletionIds') or ()), 'ins': tuple(run.get('suggestedInsertionIds') or ()),
                 'blue': _is_blue(style), 'bold': bool(style.get('bold'))}
        for ch in run['content']:
            out.append((idx, ch, flags))
            idx += _units16(ch)
    while out and out[-1][1] == '\n': out.pop()
    return out


def _split(chars):
    """Sentences of one paragraph: ends at 。！？ (with closing quotes kept), never inside 「」."""
    visible = [c for c in chars if not c[2]['del']]
    parts, cur, depth = [], [], 0
    i = 0
    while i < len(visible):
        c = visible[i]
        cur.append(c)
        ch = c[1]
        if ch in '「『（(': depth += 1
        elif ch in '」』）)' and depth: depth -= 1
        if ch in END and depth == 0:
            while i + 1 < len(visible) and (visible[i + 1][1] in CLOSE or visible[i + 1][1] in END):
                i += 1; cur.append(visible[i])
            parts.append(cur); cur = []
            while i + 1 < len(visible) and visible[i + 1][1] in ' 　':
                i += 1
        i += 1
    if cur and ''.join(c[1] for c in cur).strip(): parts.append(cur)
    return parts


def _speakable(part):
    """What the voice says: the sentence without blue stage notes and without ［…］ notes."""
    text = ''.join(c[1] for c in part if not c[2]['blue'])
    text = re.sub(r'［[^］]*］|\[[^\]]*\]', '', text)
    text = text.replace('**', '')
    return re.sub(r'\s+', ' ', text).strip()


def _raw(part):
    return ''.join(c[1] for c in part)


def _segs(chars):
    """A unit's characters as runs the screen draws: suggested insertions and deletions (with their suggestion id),
    blue stage notes and bold are kept apart."""
    out = []
    for _, ch, f in chars:
        key = (f['ins'][0] if f['ins'] else None, f['del'][0] if f['del'] else None, f['blue'], f['bold'])
        if out and out[-1][0] == key: out[-1][1].append(ch)
        else: out.append((key, [ch]))
    segs = []
    for (ins, dele, blue, bold), cs in out:
        seg = {'t': ''.join(cs)}
        if ins: seg['ins'] = ins
        if dele: seg['del'] = dele
        if blue: seg['blue'] = True
        if bold: seg['b'] = True
        segs.append(seg)
    return segs


def _image(doc, element):
    obj = (doc.get('inlineObjects') or {}).get((element.get('inlineObjectElement') or {}).get('inlineObjectId'), {})
    emb = (obj.get('inlineObjectProperties') or {}).get('embeddedObject') or {}
    return (emb.get('imageProperties') or {}).get('contentUri')


def outline(doc):
    """The doc cut into what the screen shows: the title, the top part (thumbnail, title, aim) with its pictures, and
    the script's headings, notes and sentences. Only sentences are spoken. Suggestions are shown as they are in the doc
    (each unit carries ``segs``); the voice reads them as if accepted."""
    content = doc.get('body', {}).get('content', [])
    units, mode, seen_script = [], 'script', any(
        (el.get('paragraph') and ''.join(e.get('textRun', {}).get('content', '') for e in el['paragraph'].get('elements', [])).strip().startswith(SCRIPT_HEADING))
        for el in content)
    if seen_script: mode = 'before'
    section = ''
    for pi, el in enumerate(content):
        p = el.get('paragraph')
        if not p: continue
        chars = _chars(p)
        text = ''.join(c[1] for c in chars if not c[2]['del']).strip()
        style = (p.get('paragraphStyle') or {}).get('namedStyleType', 'NORMAL_TEXT')
        if mode != 'script':
            for e in p.get('elements', []):
                src = e.get('inlineObjectElement') and _image(doc, e)
                if src: units.append({'kind': 'image', 'src': src})
        if not text:
            # A paragraph whose every character is a suggested deletion still shows, struck through.
            if ''.join(c[1] for c in chars).strip() and any(c[2]['del'] for c in chars):
                units.append({'kind': 'gone', 'text': ''.join(c[1] for c in chars).strip(), 'segs': _segs(chars),
                              'para': pi, **({'section': 'top'} if mode != 'script' else {})})
            continue
        if style == 'TITLE' or style == 'HEADING_1':
            units.append({'kind': 'title', 'text': text}); continue
        if text.startswith('◎'):
            if text.startswith(SCRIPT_HEADING): mode = 'script'
            elif any(text.startswith(h) for h in SKIP_HEADINGS): mode = 'before' if seen_script else 'skip'
            elif mode == 'script':
                # A ◎ line inside the script (◎追加特典① …) is a small heading of the script, not a new top part.
                # As a top-level heading the screen filed everything after it under 「読みません」 (11/18).
                section = text
                units.append({'kind': 'heading', 'level': 3, 'text': text, 'read': True, 'segs': _segs(chars)}); continue
            units.append({'kind': 'heading', 'level': 1, 'text': text, 'read': mode == 'script'}); continue
        if mode != 'script':
            units.append({'kind': 'note', 'text': text, 'section': 'top', 'segs': _segs(chars)}); continue
        if style in ('HEADING_2', 'HEADING_3') or re.match(r'^【\d+】', text) or text.startswith('▼'):
            level = 2 if (style == 'HEADING_2' or text.startswith('【')) else 3
            section = text
            units.append({'kind': 'heading', 'level': level, 'text': text, 'read': True, 'segs': _segs(chars)}); continue
        visible = [c for c in chars if not c[2]['del']]
        if all(c[2]['blue'] or not c[1].strip() for c in visible) or text.startswith('［'):
            units.append({'kind': 'note', 'text': text, 'para': pi, 'segs': _segs(chars)}); continue
        mine = []      # (unit, end) of this paragraph, to hand every character (deleted ones too) to a unit
        for part in _split(chars):
            while part and not part[0][1].strip(): part = part[1:]
            while part and not part[-1][1].strip(): part = part[:-1]
            if not part: continue
            speak = _speakable(part)
            end = part[-1][0] + _units16(part[-1][1])
            if not speak or not re.search(r'[\w぀-ヿ一-鿿]', speak):
                u = {'kind': 'note', 'text': _raw(part).strip(), 'para': pi}
                units.append(u); mine.append((u, end)); continue
            start = part[0][0]
            inside = [c for c in chars if start <= c[0] < end]
            u = {'kind': 'say', 'text': _raw(part).strip(), 'speak': speak, 'para': pi, 'start': start, 'end': end,
                 'bmask': ''.join('1' if c[2]['bold'] else '0' for c in part),
                 'bold': all(c[2]['bold'] for c in part if c[1].strip()),
                 'locked': any(c[2]['ins'] or c[2]['del'] for c in inside), 'section': section, 'gap': 's'}
            units.append(u); mine.append((u, end))
        # Characters between sentences (spaces, a deleted sentence) go to the sentence after them.
        own = [[] for _ in mine]
        for c in chars:
            k = next((i for i, (_, end) in enumerate(mine) if c[0] < end), len(mine) - 1)
            if k >= 0: own[k].append(c)
        for (u, _), cs in zip(mine, own):
            u['segs'] = _segs(cs)
            if u['kind'] == 'say' and any(c[2]['ins'] or c[2]['del'] for c in cs): u['locked'] = True
    # One short pause after every sentence: the owner wanted the whole script to run on without stops at paragraphs
    # and sections (11/19, 「段落ごとに…多少の間がある…それも無くして全部一気に再生できるように」).
    return units


def suggestions_of(units):
    """Each suggestion once, with the text it adds and removes and the first unit it shows in."""
    out = {}
    for u in units:
        for seg in u.get('segs') or ():
            for kind in ('ins', 'del'):
                sid = seg.get(kind)
                if not sid: continue
                s = out.setdefault(sid, {'id': sid, 'ins': '', 'del': '', 'n': u['n']})
                s[kind] += seg['t']
    return list(out.values())


def read(doc_id, voice=DEFAULT_VOICE):
    doc = fetch(doc_id)
    units = outline(doc)
    for n, u in enumerate(units):
        u['n'] = n
        if u['kind'] == 'say':
            u['key'] = clip_key(u['speak'], voice, u['gap'])
            u['ready'] = (CACHE / f"{u['key']}.mp3").exists()
            u['seconds'] = _meta(u['key']).get('seconds')
    title = doc.get('title', '')
    watch_soon(doc_id)
    return {'doc_id': doc_id, 'title': title, 'revision': doc.get('revisionId'), 'version': doc.get('revisionId'),
            'voice': voice, 'voices': [{'id': v['id'], 'name': v['name']} for v in VOICES], 'units': units,
            'suggestions': suggestions_of(units)}


def version(doc_id):
    """The doc's revision, read alone (cheap). Drive's file version lagged an edit by over 20 s on 11/18; this does not."""
    for account in ACCOUNTS:
        try:
            return _docs('GET', doc_id, account, params={'fields': 'revisionId'}).get('revisionId')
        except Exception:
            continue
    return None


def edit_requests(start, old, new, bmask=''):
    """Docs API requests that turn ``old`` (which sits at ``start``) into ``new`` touching only what differs.
    Work from the end so earlier positions stay valid. New text takes the boldness of the text it replaces (the Docs
    API would otherwise give it the boldness of the character before it, e.g. bold right after a bold phrase)."""
    bold = lambda i: bool(bmask) and 0 <= i < len(bmask) and bmask[i] == '1'
    pos, acc = [], start
    for ch in old:
        pos.append(acc); acc += _units16(ch)
    pos.append(acc)
    reqs = []
    for tag, i1, i2, j1, j2 in reversed(SequenceMatcher(None, old, new, autojunk=False).get_opcodes()):
        if tag == 'equal': continue
        if i2 > i1:
            reqs.append({'deleteContentRange': {'range': {'startIndex': pos[i1], 'endIndex': pos[i2]}}})
        if j2 > j1:
            text = new[j1:j2]
            reqs.append({'insertText': {'location': {'index': pos[i1]}, 'text': text}})
            if bmask:
                like = i1 if i1 < len(old) else i1 - 1
                reqs.append({'updateTextStyle': {'range': {'startIndex': pos[i1], 'endIndex': pos[i1] + sum(_units16(c) for c in text)},
                                                 'textStyle': {'bold': bold(like)}, 'fields': 'bold'}})
    return reqs


def edit(doc_id, old, new, para=None, start=None):
    """Replace one sentence in the doc. ``old`` is the sentence as the screen showed it; the doc is read again first
    and, when it no longer has that sentence where it was (or anywhere, uniquely), nothing is written."""
    new = (new or '').replace('\r', '').replace('\n', ' ').strip()
    if not new: raise ListenError('空の文にはできません。文を消す時はドキュメントで消してください。')
    _follow(doc_id)
    doc = fetch(doc_id)
    says = [u for u in outline(doc) if u['kind'] == 'say']
    hit = [u for u in says if u['text'] == old and u.get('start') == start]
    if not hit:
        hit = [u for u in says if u['text'] == old]
        if len(hit) != 1:
            raise ListenError('ドキュメントの方でこの文が直されていたので、ドキュメントから読み直しました。', 409)
    u = hit[0]
    if u['locked']:
        raise ListenError('この文には提案（提案モードの直し）が入っているので、ここでは直せません。ドキュメントで提案を決めてから直してください。', 409)
    if new == old: return {'changed': False}
    reqs = edit_requests(u['start'], old, new, u.get('bmask', ''))
    _docs('POST', f'{doc_id}:batchUpdate', doc['_account'],
          body={'requests': reqs, 'writeControl': {'requiredRevisionId': doc['revisionId']}})
    _log_owner_edit(doc_id, doc.get('title', ''), old, new)
    return {'changed': True, 'requests': len(reqs)}


def _log_owner_edit(doc_id, title, old, new):
    # The doc shows these edits under Dan's Google account; this file keeps that they were the owner's words. The
    # learning reads it (script_learning.owner_actions).
    _log_owner_action(doc_id, title, action='edit', before=old, after=new)


def _log_owner_action(doc_id, title, **fields):
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'owner_edits.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'doc_id': doc_id, 'title': title, 'by': 'owner',
                            'via': 'script-listen', **fields}, ensure_ascii=False) + '\n')


# ---------------------------------------------------------------- suggestions (accept / reject on the screen)

def decide(doc_id, sid, accept):
    """Accept or reject one suggestion the way Docs does. The Docs API has no accept/reject, so the same result is
    written: text that stays is deleted and written again as plain text with its style, text that goes is deleted.
    Tried on a copy 11/19: Docs then shows the suggestion as settled."""
    _follow(doc_id)
    doc = fetch(doc_id)
    content = doc.get('body', {}).get('content', [])
    body_end = content[-1].get('endIndex') if content else None
    runs = []
    paras = [el for el in content if el.get('paragraph')]
    for k, el in enumerate(paras):
        p = el['paragraph']
        pstyle = (p.get('paragraphStyle') or {}).get('namedStyleType', 'NORMAL_TEXT')
        nxt = (paras[k + 1]['paragraph'].get('paragraphStyle') or {}).get('namedStyleType', 'NORMAL_TEXT') if k + 1 < len(paras) else None
        for e in p.get('elements', []):
            r = e.get('textRun')
            if not r: continue
            ins, dele = r.get('suggestedInsertionIds') or [], r.get('suggestedDeletionIds') or []
            if sid not in ins and sid not in dele: continue
            if set(ins) | set(dele) != {sid}:
                raise ListenError('この提案は別の提案と重なっているので、ドキュメントで決めてください。', 409)
            end = e.get('endIndex', e['startIndex'] + sum(_units16(c) for c in r['content']))
            runs.append((e['startIndex'], end, 'ins' if sid in ins else 'del', r['content'], r.get('textStyle') or {}, pstyle, nxt))
    if not runs:
        raise ListenError('この提案はもうありません。ドキュメントの方で決められたかもしれません。', 409)
    text_reqs, style_reqs = decide_requests(runs, accept, body_end)
    _docs('POST', f'{doc_id}:batchUpdate', doc['_account'],
          body={'requests': text_reqs, 'writeControl': {'requiredRevisionId': doc['revisionId']}})
    if style_reqs:
        _docs('POST', f'{doc_id}:batchUpdate', doc['_account'], body={'requests': style_reqs})
    added = ''.join(r[3] for r in runs if r[2] == 'ins').strip()
    removed = ''.join(r[3] for r in runs if r[2] == 'del').strip()
    _log_owner_action(doc_id, doc.get('title', ''), action='accept' if accept else 'reject', suggestion=sid,
                      added=added, removed=removed)
    return {'done': True}


def decide_requests(runs, accept, body_end=None):
    """runs: (start, end, 'ins'|'del', text, textStyle, paragraph style, next paragraph's style) of one suggestion.
    Returns (text requests, style requests). The styles go in a second write at the final positions: written in the
    same write, text put back next to the suggestion's other runs still counted as suggested and lost its bold (11/19)."""
    text_reqs, kept = [], []
    for start, end, kind, text, style, pstyle, nxt in sorted(runs, key=lambda r: r[0], reverse=True):
        if body_end and end >= body_end:          # the doc's last newline cannot be deleted
            end, text = end - 1, text[:-1]
            if end <= start: continue
        text_reqs.append({'deleteContentRange': {'range': {'startIndex': start, 'endIndex': end}}})
        if (kind == 'ins') != accept: continue     # this text goes
        text_reqs.append({'insertText': {'location': {'index': start}, 'text': text}})
        kept.append((start, end, text, style, pstyle, nxt))
    gone = sorted((r[0], r[1]) for r in runs if (r[2] == 'ins') != accept)
    style_reqs = []
    for start, end, text, style, pstyle, nxt in sorted(kept):
        at = start - sum(min(b, start) - a for a, b in gone if a < start)
        size = sum(_units16(c) for c in text)
        # A weight in weightedFontFamily wins over bold (11/19: bold text came back thin); keep only the family.
        style = dict(style)
        family = (style.pop('weightedFontFamily', None) or {}).get('fontFamily')
        if family: style['weightedFontFamily'] = {'fontFamily': family}
        style_reqs.append({'updateTextStyle': {'range': {'startIndex': at, 'endIndex': at + size}, 'textStyle': style, 'fields': '*'}})
        if text.endswith('\n'):
            # Deleting the newline joined two paragraphs; writing it again split them with one style. Put both back.
            style_reqs.append({'updateParagraphStyle': {'range': {'startIndex': at, 'endIndex': at + size},
                                                        'paragraphStyle': {'namedStyleType': pstyle}, 'fields': 'namedStyleType'}})
            if nxt:
                style_reqs.append({'updateParagraphStyle': {'range': {'startIndex': at + size, 'endIndex': at + size + 1},
                                                            'paragraphStyle': {'namedStyleType': nxt}, 'fields': 'namedStyleType'}})
    # Paragraph styles first: setting a paragraph's named style clears the text styles inside it (11/19, bold was lost).
    style_reqs.sort(key=lambda r: 'updateParagraphStyle' not in r)
    return text_reqs, style_reqs


# ---------------------------------------------------------------- comments (the doc's own comments, both ways)
#
# The page writes and reads the doc's comments through Drive, so a comment made here is the same comment the owner
# would make in Google Docs: the comment watcher (gdoc_events) hands it to Dan, Dan answers in the thread and fixes the
# text as suggestions, and the learning (script_learning) keeps it. Docs shows comments made through the API in its list
# without a place in the text ("元のコンテンツは削除されました"); the page places them by the quoted words.

ANCHORS = STATE / 'anchors.json'
_private: dict = {}
_watching: set = set()


def _account(doc_id):
    from app.services import gdoc_events as E
    with E.db() as c:
        row = c.execute('SELECT account FROM docs WHERE file_id=?', (doc_id,)).fetchone()
    return row['account'] if row else ACCOUNTS[0]


def owner_only(doc_id):
    """Only the owner's accounts can open the doc (cached 10 min). Dan answers comments only there: elsewhere a
    customer would read the answers."""
    from app.services import gdoc_events as E
    hit = _private.get(doc_id)
    if hit and time.time() - hit[1] < 600: return hit[0]
    value = E.owner_only(_account(doc_id), doc_id)
    _private[doc_id] = (value, time.time())
    return value


def ensure_watched(doc_id):
    """The comment watcher and the learning both follow this doc. True when they do."""
    from app.services import gdoc_events as E
    from app.services import script_learning as L
    with E.db() as c:
        row = c.execute('SELECT * FROM docs WHERE file_id=?', (doc_id,)).fetchone()
    if not row:
        if not owner_only(doc_id): return False
        try: E.register(doc_id, E.room_for_file(doc_id), ACCOUNTS[0])
        except ValueError: pass             # registered meanwhile
        with E.db() as c:
            row = c.execute('SELECT * FROM docs WHERE file_id=?', (doc_id,)).fetchone()
    with L.db() as c:
        target = c.execute('SELECT enabled FROM targets WHERE file_id=?', (doc_id,)).fetchone()
    if not target:
        # The first snapshot is the starting point the owner's later edits are compared with.
        L.enable(dict(row))
    return True


def watch_soon(doc_id):
    """Opening a script on the screen starts following it (once per process), so its first edit is already learned."""
    if doc_id in _watching: return
    _watching.add(doc_id)

    def run():
        try: ensure_watched(doc_id)
        except Exception:
            import logging
            logging.exception('script-listen could not follow %s', doc_id)
            _watching.discard(doc_id)
    threading.Thread(target=run, name='script-listen-watch', daemon=True).start()


def _follow(doc_id):
    """Before the owner's first write: the learning's starting point must be taken before it, not after."""
    try: ensure_watched(doc_id)
    except Exception:
        import logging
        logging.exception('script-listen could not follow %s', doc_id)


def _poke(doc_id):
    """Tell the comment watcher to read the doc now instead of waiting for Google's notice."""
    from app.services import gdoc_events as E
    with E.db() as c:
        c.execute('UPDATE docs SET dirty=dirty+1 WHERE file_id=?', (doc_id,))
    E.signal()


def _anchors():
    try: return json.loads(ANCHORS.read_text())
    except Exception: return {}


def _who(item, private):
    text = (item.get('content') or '').strip()
    if text.startswith(('ダン：', 'ダン:', '【変えた所】', '【根拠】')): return 'dan'
    if item.get('author', {}).get('me') or private: return 'owner'
    return 'other'


def comments(doc_id):
    """The doc's threads, oldest first, with who wrote each message and whether Dan is working on it."""
    import html
    from app.services import gdoc_drive as G
    from app.services import gdoc_events as E
    threads = G.comments(_account(doc_id), doc_id)
    private = owner_only(doc_id)
    busy = {}
    with E.db() as c:
        for r in c.execute("SELECT payload,status FROM batches WHERE file_id=? AND status IN ('pending','running','needs_room')",
                           (doc_id,)):
            for ch in json.loads(r['payload']):
                busy[ch['comment_id']] = r['status']
    anchors = _anchors()
    out = []
    for t in threads:
        if t.get('deleted'): continue
        msgs = []
        for item in [t, *t.get('replies', [])]:
            if item.get('deleted'): continue
            text = (item.get('content') or '').strip()
            if not text:
                if item.get('action'):
                    msgs.append({'id': item['id'], 'action': item['action'], 'who': _who(item, private), 'at': item.get('createdTime')})
                continue
            msgs.append({'id': item['id'], 'who': _who(item, private), 'name': (item.get('author') or {}).get('displayName'),
                         'text': text, 'at': item.get('createdTime')})
        quote = html.unescape((t.get('quotedFileContent') or {}).get('value') or '')
        out.append({'id': t['id'], 'quote': quote, 'resolved': bool(t.get('resolved')), 'messages': msgs,
                    'at': t.get('createdTime'), 'working': busy.get(t['id']), 'start': anchors.get(t['id'])})
    out.sort(key=lambda x: x['at'] or '')
    return {'threads': out, 'can_comment': private}


def _owner_words(text):
    text = (text or '').strip()
    if not text: raise ListenError('空のままでは送れません。')
    if text.startswith(('ダン：', 'ダン:', '【変えた所】', '【根拠】')):
        raise ListenError('「ダン：」で始まる文はダンの返事と見分けられないので、別の書き出しにしてください。')
    return text


def add_comment(doc_id, quote, text, start=None):
    from app.services import gdoc_drive as G
    text = _owner_words(text)
    if not ensure_watched(doc_id):
        raise ListenError('お客さんも開けるドキュメントなので、ここからはコメントできません（ダンの返事がお客さんにも見えるため）。'
                          '作業用の台本で書いてください。', 403)
    body = {'content': text}
    quote = (quote or '').strip()
    if quote: body['quotedFileContent'] = {'mimeType': 'text/html', 'value': quote}
    made = G.request(_account(doc_id), 'POST', f'files/{doc_id}/comments', body, {'fields': 'id'})
    if start is not None:
        STATE.mkdir(parents=True, exist_ok=True)
        anchors = _anchors(); anchors[made['id']] = start
        ANCHORS.write_text(json.dumps(anchors))
    _poke(doc_id)
    return {'id': made['id']}


def reply(doc_id, comment_id, text):
    from app.services import gdoc_drive as G
    text = _owner_words(text)
    if not ensure_watched(doc_id):
        raise ListenError('お客さんも開けるドキュメントなので、ここからは返事を書けません。', 403)
    made = G.request(_account(doc_id), 'POST', f'files/{doc_id}/comments/{comment_id}/replies', {'content': text}, {'fields': 'id'})
    _poke(doc_id)
    return {'id': made['id']}


def settle(doc_id, comment_id, reopen=False):
    from app.services import gdoc_drive as G
    G.request(_account(doc_id), 'POST', f'files/{doc_id}/comments/{comment_id}/replies',
              {'action': 'reopen' if reopen else 'resolve', 'content': ''}, {'fields': 'id'})
    return {'done': True}


# ---------------------------------------------------------------- speech

def clip_key(speak, voice, gap):
    return hashlib.sha1(f'{RECIPE}|{voice}|{gap}|{speak}'.encode()).hexdigest()[:24]


def _meta(key):
    try: return json.loads((CACHE / f'{key}.json').read_text())
    except Exception: return {}


_styles: dict = {}
_engine_lock = threading.Lock()


def engine_alive():
    try:
        return httpx.get(ENGINE + '/version', timeout=2).status_code == 200
    except Exception:
        return False


def _wake_engine():
    """The engine is a launchd job (scripts/install_aivis_speech.py); ask launchd to start it when it is not up."""
    if engine_alive(): return True
    subprocess.run(['launchctl', 'kickstart', f'gui/{os.getuid()}/com.dan.aivis-speech'], capture_output=True)
    for _ in range(60):
        if engine_alive(): return True
        time.sleep(1)
    return False


def _style(voice):
    if voice in _styles: return _styles[voice]
    spec = next((v for v in VOICES if v['id'] == voice), None)
    if not spec: raise ListenError('その声はありません。')
    speakers = httpx.get(ENGINE + '/speakers', timeout=10).json()
    for s in speakers:
        if s['name'] == spec['speaker']:
            for st in s['styles']:
                if st['name'] == spec['style']:
                    _styles[voice] = st['id']; return st['id']
    raise ListenError(f"声「{spec['name']}」が読み上げの道具に入っていません。", 503)


def _trim(samples, rate, floor_db=-42.0, keep=0.03):
    import numpy as np
    if not len(samples): return samples
    win = max(1, int(rate * 0.01))
    n = len(samples) // win
    if n == 0: return samples
    frames = samples[:n * win].reshape(n, win).astype('float64')
    rms = np.sqrt((frames ** 2).mean(axis=1)) + 1e-9
    db = 20 * np.log10(rms / 32768.0)
    loud = np.where(db > floor_db)[0]
    if not len(loud): return samples
    a = max(0, loud[0] * win - int(rate * keep))
    b = min(len(samples), (loud[-1] + 1) * win + int(rate * keep))
    return samples[a:b]


_urgent = 0                # clips the listener is waiting for; making ahead steps aside for them
_urgent_lock = threading.Lock()


def synthesize(speak, voice, gap, urgent=True):
    """Make one clip (mp3) unless it is already there. Returns its key. A clip the listener waits for (urgent) goes
    before the clips being made ahead."""
    global _urgent
    key = clip_key(speak, voice, gap)
    path = CACHE / f'{key}.mp3'
    if path.exists(): return key
    if urgent:
        with _urgent_lock: _urgent += 1
    try:
        return _make(key, path, speak, voice, gap)
    finally:
        if urgent:
            with _urgent_lock: _urgent -= 1


def _make(key, path, speak, voice, gap):
    import numpy as np
    import soundfile as sf
    with _engine_lock:
        if path.exists(): return key
        if not _wake_engine():
            raise ListenError('読み上げの道具が起きていません。少し待ってからもう一度押してください。', 503)
        sid = _style(voice)
        with httpx.Client(base_url=ENGINE, timeout=120) as c:
            q = c.post('/audio_query', params={'text': speak, 'speaker': sid})
            q.raise_for_status(); q = q.json()
            q['prePhonemeLength'] = 0.0; q['postPhonemeLength'] = 0.0; q['pauseLengthScale'] = PAUSE_SCALE
            w = c.post('/synthesis', params={'speaker': sid}, json=q)
            w.raise_for_status()
        data, rate = sf.read(io.BytesIO(w.content), dtype='int16')
        if data.ndim > 1: data = data.mean(axis=1).astype('int16')
        data = _trim(data, rate)
        data = np.concatenate([data, np.zeros(int(rate * GAPS[gap]), dtype='int16')])
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp.mp3')
        proc = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-f', 's16le', '-ar', str(rate), '-ac', '1', '-i', 'pipe:0',
                               '-c:a', 'libmp3lame', '-b:a', '64k', str(tmp)], input=data.tobytes(), capture_output=True)
        if proc.returncode != 0:
            raise ListenError('音声を作れませんでした。', 500)
        (CACHE / f'{key}.json').write_text(json.dumps({'seconds': round(len(data) / rate, 3), 'speak': speak, 'voice': voice}))
        tmp.replace(path)
    return key


# ---------------------------------------------------------------- making ahead

_queue_lock = threading.Lock()
_queue: list = []          # (key, speak, voice, gap) in the order they will be heard
_worker = None


def prepare(items):
    """Make the clips ahead in this order (the listener's position first). A newer call replaces the order."""
    global _worker
    with _queue_lock:
        _queue[:] = [i for i in items if not (CACHE / f'{i[0]}.mp3').exists()]
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run_queue, name='script-listen-ahead', daemon=True)
            _worker.start()
    return len(_queue)


def _run_queue():
    while True:
        while _urgent > 0: time.sleep(0.05)
        with _queue_lock:
            if not _queue: return
            key, speak, voice, gap = _queue.pop(0)
        try: synthesize(speak, voice, gap, urgent=False)
        except Exception: time.sleep(2)


def clip_path(key):
    if not re.fullmatch(r'[0-9a-f]{24}', key or ''): raise ListenError('音声が見つかりません。', 404)
    return CACHE / f'{key}.mp3'
