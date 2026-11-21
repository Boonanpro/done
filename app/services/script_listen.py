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

from app.services import script_listen_marks as M

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


class Stale(ListenError):
    """Someone wrote to the doc between reading it and writing (Dan putting in a suggestion while the owner typed)."""
    def __init__(self):
        super().__init__('ドキュメントがちょうど直されたので、読み直しました。', 409)


def _retry_stale(fn):
    """Read the doc again and write again when it moved meanwhile: the owner's change goes onto the new text (_locate).
    Before 11/21 the Docs API's「does not match the latest revision」was not recognised, came out as 500, and the
    screen threw away what the owner had just typed (本人「ダンが作業してる時に俺が手動編集した内容が巻き戻された」)."""
    import functools

    @functools.wraps(fn)
    def run(*args, **kwargs):
        for attempt in range(5):
            try: return fn(*args, **kwargs)
            except Stale:
                if attempt == 4: raise
                time.sleep(0.2 * (attempt + 1))
    return run


# ---------------------------------------------------------------- Google Docs

def _token(account):
    from app.services import gdoc_drive as G
    return G.access_token(account)


def _docs(method, path, account, body=None, params=None):
    from app.services import gdoc_drive as G
    r = G._client.request(method, 'https://docs.googleapis.com/v1/documents/' + path, timeout=40,
                          headers={'Authorization': 'Bearer ' + _token(account)}, json=body, params=params)
    if r.status_code == 404 or r.status_code == 403:
        raise ListenError('このドキュメントを開けませんでした。ダンのGoogleアカウントに共有されているか確かめてください。', 404)
    if r.status_code == 400 and ('requiredRevisionId' in r.text or 'does not match the latest revision' in r.text):
        raise Stale()
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
        # The owner's added words (script_listen_marks) have no room in the doc yet: all of them sit where they go.
        step = not run.get('_virtual')
        for ch in run['content']:
            out.append((idx, ch, flags))
            if step: idx += _units16(ch)
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
        # Pictures show where they are in the doc, in the script too (11/20 本人「スクショはどこにあるん？該当部分に
        # 貼っといて」: the screenshots Dan put under the comment line were in the doc but not on the screen).
        for e in p.get('elements', []):
            src = e.get('inlineObjectElement') and _image(doc, e)
            if not src: continue
            img = {'kind': 'image', 'src': src, 'id': e['inlineObjectElement'].get('inlineObjectId'), 'para': pi}
            sug = (e['inlineObjectElement'].get('suggestedInsertionIds') or [None])[0]
            gone = (e['inlineObjectElement'].get('suggestedDeletionIds') or [None])[0]
            if sug: img['ins'] = sug
            if gone: img['del'] = gone
            if mode != 'script': img['section'] = 'top'
            units.append(img)
        if not text:
            # A paragraph whose every character is a suggested deletion still shows, struck through.
            if ''.join(c[1] for c in chars).strip() and any(c[2]['del'] for c in chars):
                units.append({'kind': 'gone', 'text': ''.join(c[1] for c in chars).strip(), 'segs': _segs(chars),
                              'para': pi, **({'section': 'top'} if mode != 'script' else {})})
            elif units and not any(c[2]['ins'] or c[2]['del'] for c in chars):
                # An empty line shows as one, so the owner can type into it like in the doc (11/19).
                units.append({'kind': 'blank', 'text': '', 'segs': _segs(chars), 'para': pi,
                              **({'section': 'top'} if mode != 'script' else {})})
            continue
        if style == 'TITLE' or style == 'HEADING_1':
            units.append({'kind': 'title', 'text': text, 'segs': _segs(chars), 'para': pi}); continue
        if text.startswith('◎'):
            if text.startswith(SCRIPT_HEADING): mode = 'script'
            elif any(text.startswith(h) for h in SKIP_HEADINGS): mode = 'before' if seen_script else 'skip'
            elif mode == 'script':
                # A ◎ line inside the script (◎追加特典① …) is a small heading of the script, not a new top part.
                # As a top-level heading the screen filed everything after it under 「読みません」 (11/18).
                section = text
                units.append({'kind': 'heading', 'level': 3, 'text': text, 'read': True, 'segs': _segs(chars), 'para': pi}); continue
            units.append({'kind': 'heading', 'level': 1, 'text': text, 'read': mode == 'script', 'segs': _segs(chars), 'para': pi}); continue
        if mode != 'script':
            units.append({'kind': 'note', 'text': text, 'section': 'top', 'segs': _segs(chars), 'para': pi}); continue
        if style in ('HEADING_2', 'HEADING_3') or re.match(r'^【\d+】', text) or text.startswith('▼'):
            level = 2 if (style == 'HEADING_2' or text.startswith('【')) else 3
            section = text
            units.append({'kind': 'heading', 'level': level, 'text': text, 'read': True, 'segs': _segs(chars), 'para': pi}); continue
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


_image_cache: dict = {}
IMAGE_WIDTH = 1000          # pictures travel inside the answer, so they are made small first


def _small(data):
    """A picture as a JPEG at most IMAGE_WIDTH wide (a screenshot is 1 MB as a PNG, 80 kB like this)."""
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    if im.mode in ('RGBA', 'LA', 'P'):
        im = im.convert('RGBA')
        bg = Image.new('RGB', im.size, 'white')
        bg.paste(im, mask=im.split()[-1])
        im = bg
    elif im.mode != 'RGB':
        im = im.convert('RGB')
    if im.width > IMAGE_WIDTH:
        im = im.resize((IMAGE_WIDTH, round(im.height * IMAGE_WIDTH / im.width)), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, 'JPEG', quality=82, optimize=True)
    return out.getvalue()


IMAGES = STATE / 'img'
_image_links: dict = {}         # picture name -> the doc's link to it (to fetch it when the browser first asks)
_image_locks: dict = {}       # one per picture: several pictures are fetched at the same time
_IMAGE_EXTS = ('jpg', 'png', 'gif', 'webp')


def _image_name(key):
    """The name a picture is kept under: from the picture's Google link and a secret of this machine, so the name
    cannot be guessed (an <img> opens it without the sign-in mark, like the dev-lead pictures)."""
    import hashlib, secrets
    IMAGES.mkdir(parents=True, exist_ok=True)
    salt_file = IMAGES / '.salt'
    if not salt_file.exists():
        salt_file.write_text(secrets.token_hex(16))
    return hashlib.sha256((salt_file.read_text().strip() + '|' + key).encode()).hexdigest()[:40]


def _kept_image(name):
    return next((p for p in (IMAGES / f'{name}.{e}' for e in _IMAGE_EXTS) if p.exists()), None)


def image_path(name):
    """The picture called ``name`` (from _inline_images), fetched from the doc and made small the first time it is
    asked for; None when there is no such picture."""
    if not re.fullmatch(r'[0-9a-f]{40}', name or ''):
        return None
    have = _kept_image(name)
    if have:
        return have
    src = _image_links.get(name)
    if not src:
        links = IMAGES / 'links.json'
        try: src = json.loads(links.read_text()).get(name) if links.exists() else None
        except Exception: src = None
    if not src:
        return None
    with _image_locks.setdefault(name, threading.Lock()):
        have = _kept_image(name)
        if have:
            return have
        r = httpx.get(src, timeout=20, follow_redirects=True)
        r.raise_for_status()
        if len(r.content) > 20_000_000:
            return None
        try:
            data, ext = _small(r.content), 'jpg'
        except Exception:
            kind = r.headers.get('content-type', 'image/jpeg').split(';')[0]
            data, ext = r.content, {'image/png': 'png', 'image/gif': 'gif', 'image/webp': 'webp'}.get(kind, 'jpg')
        out = IMAGES / f'{name}.{ext}'
        tmp = IMAGES / f'{name}.{ext}.part'
        tmp.write_bytes(data)
        tmp.replace(out)
        return out


def _inline_images(units, most=40):
    """The doc's picture links only open from a server (a browser signed in to Google gets refused, 11/19), so the
    answer gives each picture an address of ours (/api/v1/script-listen/img/<name>); the server fetches the picture
    from the doc, makes it small and keeps it when the browser first asks. 11/21 本人「台本読み上げページも遅い」: the
    pictures used to travel inside the answer as data (620 kB of the 690 kB the screen waited for on every opening) and
    the answer waited for Google to send them (4–5 s whenever they were not in memory)."""
    fresh = {}
    for u in [x for x in units if x['kind'] == 'image'][:most]:
        key = u['src'].split('?')[0]
        name = _image_cache.get(key)
        if not name:
            name = _image_cache[key] = _image_name(key)
            if len(_image_cache) > 400: _image_cache.pop(next(iter(_image_cache)))
        if _image_links.get(name) != u['src']:
            fresh[name] = u['src']
        u['src'] = f'/api/v1/script-listen/img/{name}'
    if fresh:
        _image_links.update(fresh)
        # Kept on disk too (the doc's links change their query part but last for days), so an address handed out
        # before a restart still opens.
        try:
            links = IMAGES / 'links.json'
            have = json.loads(links.read_text()) if links.exists() else {}
            have.update(fresh)
            if len(have) > 2000: have = dict(list(have.items())[-2000:])
            tmp = IMAGES / 'links.json.part'
            tmp.write_text(json.dumps(have))
            tmp.replace(links)
        except Exception:
            pass
        for name in fresh:   # fetch them now, so the browser rarely waits
            if not _kept_image(name):
                threading.Thread(target=_fetch_quietly, args=(name,), daemon=True).start()


def _fetch_quietly(name):
    try: image_path(name)
    except Exception: pass


def suggestions_of(units, kept=()):
    """Each suggestion once, with the text it adds and removes and the first unit it shows in. ``by`` owner: written
    in suggestion mode on this screen (kept here, not in the doc); client: what the other side changed in the copy
    they were sent (script_share), kept the same way. ``kept``: the screen's suggestions (for whose each is)."""
    whose = {k.get('id'): k.get('by') for k in kept or ()}
    out = {}
    for u in units:
        if u['kind'] == 'image':
            for kind in ('ins', 'del'):
                sid = u.get(kind)
                if sid:
                    s = out.setdefault(sid, {'id': sid, 'ins': '', 'del': '', 'n': u['n'], 'by': 'doc'})
                    s[kind] += '［画像］'
            continue
        for seg in u.get('segs') or ():
            for kind in ('ins', 'del'):
                sid = seg.get(kind)
                if not sid: continue
                by = ('client' if whose.get(sid) == 'client' else 'owner') if M.is_owner(sid) else 'doc'
                s = out.setdefault(sid, {'id': sid, 'ins': '', 'del': '', 'n': u['n'], 'by': by})
                s[kind] += seg['t']
    return list(out.values())


def view(doc_id, doc=None):
    """The doc with the owner's own suggestions laid in: (doc, the suggestions kept for it, {sid: paragraph})."""
    doc = doc or fetch(doc_id)
    sugs = M.load(OWNER_SUGS, doc_id)
    shown, placed = M.overlay(doc, sugs)
    return shown, sugs, placed


def read(doc_id, voice=DEFAULT_VOICE):
    doc, kept, _ = view(doc_id)
    units = outline(doc)
    for n, u in enumerate(units):
        u['n'] = n
        if u['kind'] == 'say':
            u['key'] = clip_key(u['speak'], voice, u['gap'])
            u['ready'] = (CACHE / f"{u['key']}.mp3").exists()
            u['seconds'] = _meta(u['key']).get('seconds')
    try:
        from app.services import script_listen_thumbs as T
        T.annotate(doc_id, units)
    except Exception:
        pass
    _inline_images(units)
    title = doc.get('title', '')
    watch_soon(doc_id)
    return {'doc_id': doc_id, 'title': title, 'revision': doc.get('revisionId'), 'version': doc.get('revisionId'),
            'voice': voice, 'voices': [{'id': v['id'], 'name': v['name']} for v in VOICES], 'units': units,
            'suggestions': suggestions_of(units, kept)}


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


@_retry_stale
def edit(doc_id, old, new, para=None, start=None):
    """Replace one sentence in the doc. ``old`` is the sentence as the screen showed it; the doc is read again first
    and, when it no longer has that sentence where it was (or anywhere, uniquely), nothing is written."""
    new = (new or '').replace('\r', '').replace('\n', ' ').strip()
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
    # Emptying a sentence deletes it (with the space after it, or with its paragraph when it was the whole paragraph).
    reqs = delete_requests(doc, u) if not new else edit_requests(u['start'], old, new, u.get('bmask', ''))
    _docs('POST', f'{doc_id}:batchUpdate', doc['_account'],
          body={'requests': reqs, 'writeControl': {'requiredRevisionId': doc['revisionId']}})
    _log_owner_edit(doc_id, doc.get('title', ''), old, new)
    return {'changed': True, 'requests': len(reqs)}


def _para_span(doc, para_from, para_to):
    """The paragraphs ``para_from``..``para_to`` of the doc as one text (paragraphs joined by '\n'), the doc index of
    every character plus the end, and their boldness. None when one of them is not a plain paragraph."""
    content = doc.get('body', {}).get('content', [])
    if not (0 <= para_from <= para_to < len(content)): return None
    text, pos, bold, locked = [], [], [], []
    for pi in range(para_from, para_to + 1):
        el = content[pi]
        p = el.get('paragraph')
        if p is None: return None
        if pi > para_from:
            text.append('\n'); pos.append(content[pi - 1]['endIndex'] - 1); bold.append('0'); locked.append(False)
        for idx, ch, f in _chars(p):
            locked.append(bool(f['ins'] or f['del']))
            text.append(ch); pos.append(idx); bold.append('1' if f['bold'] else '0')
    pos.append(content[para_to]['endIndex'] - 1)
    return ''.join(text), pos, ''.join(bold), locked


def touches_suggestion(old, new, locked):
    """Whether turning ``old`` into ``new`` changes a character of a suggestion (or types inside one). Text next to a
    suggestion can still be changed, like in the doc."""
    for tag, i1, i2, _, _ in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == 'equal': continue
        if any(locked[i1:i2]): return True
        if i1 == i2 and 0 < i1 < len(old) and locked[i1 - 1] and locked[i1]: return True
    return False


def replace_requests(pos, old, new, old_bmask, new_bmask, ops=None):
    """Docs API requests that turn ``old`` (characters at ``pos``, '\n' between paragraphs) into ``new``. Text first,
    from the end; then boldness, in the coordinates of the new text, only where it differs from what was there (so the
    bold of headings, which comes from their named style, is left alone)."""
    reqs, styles = [], []
    base = pos[0]
    npos, acc = [], base
    for ch in new:
        npos.append(acc); acc += _units16(ch)
    npos.append(acc)
    nb = lambda j: j < len(new_bmask) and new_bmask[j] == '1'
    ob = lambda i: i < len(old_bmask) and old_bmask[i] == '1'
    want = {}
    ops = ops or SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
    for tag, i1, i2, j1, j2 in reversed(ops):
        if tag == 'equal': continue
        if i2 > i1:
            reqs.append({'deleteContentRange': {'range': {'startIndex': pos[i1], 'endIndex': pos[i2]}}})
        if j2 > j1:
            reqs.append({'insertText': {'location': {'index': pos[i1]}, 'text': new[j1:j2]}})
    for tag, i1, i2, j1, j2 in ops:
        if tag == 'equal':
            for k in range(i2 - i1):
                if ob(i1 + k) != nb(j1 + k): want[j1 + k] = nb(j1 + k)
        else:
            # New text takes the style of the character before it (Docs does that); set bold only where that is wrong.
            like = i1 - 1 if i1 > 0 and old[i1 - 1] != '\n' else i2 if i2 < len(old) else i1 - 1
            for j in range(j1, j2):
                if nb(j) != (like >= 0 and ob(like)): want[j] = nb(j)
    run = None
    for j in sorted(want):
        if new[j] == '\n': continue
        if run and run[1] == j and run[2] == want[j]: run[1] = j + 1
        else:
            if run: styles.append(run)
            run = [j, j + 1, want[j]]
    if run: styles.append(run)
    for a, b, v in styles:
        reqs.append({'updateTextStyle': {'range': {'startIndex': npos[a], 'endIndex': npos[b]},
                                         'textStyle': {'bold': v}, 'fields': 'bold'}})
    return reqs


GONE_HERE = 'ドキュメントの方でここが直されていたので、ドキュメントから読み直しました。'


def _locate(shown, para_from, para_to, old, new, old_bmask, new_bmask):
    """The paragraphs the screen means, in the doc as it is now. They may have moved (paragraphs added before them)
    or been changed by someone else meanwhile (Dan's suggestion in the same paragraph, 11/20 本人「ダンがコメントを
    考えている最中の文字を編集しようとすると弾かれる」): then the owner's change goes onto the new text when the two do
    not touch the same words. Returns (para_from, para_to, tokens, end, old, new, new_bmask, rebased)."""
    got = M.tokens(shown, para_from, para_to, _chars)
    if got and M.text_of(got[0]) == old:
        return para_from, para_to, got[0], got[1], old, new, new_bmask, False
    for d in sorted(range(-40, 41), key=abs):
        if not d: continue
        g = M.tokens(shown, para_from + d, para_to + d, _chars)
        if g and M.text_of(g[0]) == old:
            return para_from + d, para_to + d, g[0], g[1], old, new, new_bmask, False
    if got:
        theirs = M.text_of(got[0])
        merged = M.rebase(old, theirs, new, new_bmask, M.bmask_of(got[0]))
        if merged:
            return para_from, para_to, got[0], got[1], theirs, merged[0], merged[1], True
    raise ListenError(GONE_HERE, 409)


@_retry_stale
def replace(doc_id, para_from, para_to, old, new, old_bmask='', new_bmask='', mode='edit', new_dmask='', _depth=0):
    """What the owner typed on the screen: paragraphs ``para_from``..``para_to`` read ``old`` on the screen and now
    read ``new`` (with '\n' where a paragraph ends; boldness as '0'/'1' per character). ``mode`` 'edit' writes it
    into the doc; 'suggest' keeps it as the owner's suggestion (the Docs API cannot write suggestions). Changing the
    words of a suggestion settles it first, the way the owner means it (script_listen_marks)."""
    if mode not in ('edit', 'suggest'): raise ListenError('書き方の指定が正しくありません。')
    new = (new or '').replace('\r', '')
    _follow(doc_id)
    with _owner_lock:
        doc = fetch(doc_id)
        shown, sugs, placed = view(doc_id, doc)
        new_bmask = (new_bmask or '')[:len(new)].ljust(len(new), '0')
        screen = new
        if mode == 'suggest' and '1' in (new_dmask or ''):
            # Letters struck on the screen are still in its text; for the change they are taken out (in suggestion
            # mode taking out = striking), so which of two same letters is struck does not hang on the comparison.
            keep = [k for k in range(len(new)) if not (k < len(new_dmask) and new_dmask[k] == '1')]
            new, new_bmask = ''.join(new[k] for k in keep), ''.join(new_bmask[k] for k in keep)
        para_from, para_to, toks, end, old, new, new_bmask, rebased = _locate(shown, para_from, para_to, old, new,
                                                                              old_bmask, new_bmask)
        # Boldness is compared on the screen's own terms (bold marks, not the heading style), so only what the owner
        # switched with Ctrl+B is written.
        if not rebased and len(old_bmask or '') == len(old):
            for t, b in zip(toks, old_bmask): t['b'] = b == '1'
        if new == old and new_bmask == M.bmask_of(toks):
            # Nothing changes; the screen may still show words the doc does not have (struck, typed again).
            return {'changed': False, 'reload': not rebased and screen != old}
        try:
            new_toks, settled = M.plan(toks, new, new_bmask, mode)
        except M.Refused as exc:
            raise ListenError(str(exc), 409)
        except M.Adopt as need:
            # Typing into Dan's suggestion: it becomes the owner's suggestion with the same words first, then the
            # change is made to it like to any owner suggestion (it stays a suggestion until 承認 / 却下).
            if _depth >= 2: raise ListenError(GONE_HERE, 409)
            _adopt(doc_id, doc, shown, sugs, need.sids, range(para_from, para_to + 1))
            out = replace(doc_id, para_from, para_to, old, new, old_bmask, new_bmask, mode, new_dmask, _depth + 1)
            return {**out, 'changed': True, 'reload': True}
        except M.Settle as need:
            # Dan's suggestion is being typed over: decide it in the doc the way the owner means it, then the rest.
            if _depth >= 2: raise ListenError(GONE_HERE, 409)
            for sid, accept in need.decisions.items(): decide(doc_id, sid, accept, by_edit=True)
            o2, ob2, n2, nb2, _ = M.drop_settled(toks, new, new_bmask, need.decisions)
            out = replace(doc_id, para_from, para_to, o2, n2, ob2, nb2, mode, '', _depth + 1)
            return {**out, 'changed': True, 'rebased': rebased or out.get('rebased', False),
                    'settled': {**need.decisions, **(out.get('settled') or {})}}
        out = _write(doc_id, doc, sugs, placed, para_from, para_to, toks, end, new_toks, mode, screen=None if rebased else screen)
        return {**out, 'rebased': rebased, 'settled': {**settled, **(out.get('settled') or {})}}


def _write(doc_id, doc, sugs, placed, para_from, para_to, toks, end, new_toks, mode, log=True, screen=None):
    """Write a planned change: the doc's own text, then the owner's suggestions in those paragraphs."""
    a, pos, abm, b, bbm, xlock, ops = M.doc_change(toks, new_toks)
    if any(any(xlock[i1:i2]) for tag, i1, i2, _, _ in ops if tag != 'equal'): raise ListenError(GONE_HERE, 409)
    content = doc['body']['content']
    reqs = []
    if (a != b or abm != bbm) and not (not b.strip('\n') and para_from == para_to == len(content) - 1 and not a):
        reqs = replace_requests(pos + [end], a, b, abm, bbm, ops)
    revision = None
    if reqs:
        done = _docs('POST', f'{doc_id}:batchUpdate', doc['_account'],
                     body={'requests': reqs, 'writeControl': {'requiredRevisionId': doc['revisionId']}})
        revision = (done.get('writeControl') or {}).get('requiredRevisionId')
    now = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    fresh = M.regroup(new_toks, para_from, now=now)
    old_here = {s['id']: s for s in sugs if para_from <= placed.get(s['id'], -1) <= para_to}
    for f in fresh:                        # an owner suggestion keeps when it was first written, and whose it was first
        if f['id'] in old_here:
            f['at'] = old_here[f['id']].get('at') or now
            for key in ('from', 'by', 'above', 'gap'):
                if old_here[f['id']].get(key): f[key] = old_here[f['id']][key]
    after = M.store_after(sugs, placed, para_from, para_to, b.count('\n') - a.count('\n'), fresh)
    if after != sugs: M.save(OWNER_SUGS, doc_id, after)
    title = doc.get('title', '')
    if log:
        if a != b: _log_owner_edit(doc_id, title, a, b)
        elif reqs: _log_owner_action(doc_id, title, action='bold', text=b)
        kept = {f['id'] for f in fresh}
        for f in fresh:
            was = old_here.get(f['id'])
            if not was or (was.get('del'), was.get('ins')) != (f['del'], f['ins']):
                _log_owner_action(doc_id, title, action='suggest', suggestion=f['id'],
                                  before=f['pre'] + f['del'] + f['post'], after=f['pre'] + f['ins'] + f['post'],
                                  **({'revised_from': f['from']} if f.get('from') else {}))
        for sid in old_here:
            if sid not in kept: _log_owner_action(doc_id, title, action='settle', suggestion=sid)
    # The screen tells its own writes from other people's by this revision. ``reload``: what the screen shows is not
    # what the doc now is (a suggestion was settled), so it reads the doc again.
    gone = [sid for sid in old_here if sid not in {f['id'] for f in fresh}]
    differs = False
    if mode == 'suggest' and not reqs and screen is not None:
        # The words struck and added again come out as no change, so the screen (still showing both) is not what the
        # doc reads now: compare what the screen shows with the doc and its suggestions as kept.
        again = M.tokens(M.overlay(doc, after)[0], para_from, para_to, _chars)
        differs = not again or M.text_of(again[0]) != screen
    return {'changed': bool(reqs) or after != sugs, 'requests': len(reqs), 'revision': revision,
            'reload': bool(gone) or differs or (mode == 'suggest' and after != sugs)}


def delete_requests(doc, u):
    content = doc.get('body', {}).get('content', [])
    el = content[u['para']] if 0 <= u.get('para', -1) < len(content) else {}
    p = el.get('paragraph') or {}
    whole = ''.join(c[1] for c in _chars(p) if not c[2]['del']).strip() == u['text']
    if whole and el.get('endIndex') and el is not content[-1]:
        return [{'deleteContentRange': {'range': {'startIndex': el['startIndex'], 'endIndex': el['endIndex']}}}]
    end = u['end']
    after = next((c for c in _chars(p) if c[0] == end), None)
    if after and after[1] in ' 　': end += _units16(after[1])
    return [{'deleteContentRange': {'range': {'startIndex': u['start'], 'endIndex': end}}}]


IMAGE_TYPES = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/gif': '.gif', 'image/webp': '.png'}
PAGE_WIDTH_PT = 468         # the doc's text width (612 pt page, 72 pt margins)


def image_requests(doc, after_para, uri, width_pt):
    """A new paragraph holding the picture right after paragraph ``after_para`` (a plain paragraph, not a heading)."""
    content = doc.get('body', {}).get('content', [])
    if not (0 <= after_para < len(content)) or 'paragraph' not in content[after_para]:
        raise ListenError('画像を入れる場所が分かりませんでした。入れたい所の文を押してから、もう一度貼ってください。', 409)
    end = content[after_para]['endIndex']
    return [
        {'insertText': {'location': {'index': end - 1}, 'text': '\n'}},
        {'updateParagraphStyle': {'range': {'startIndex': end, 'endIndex': end + 1},
                                  'paragraphStyle': {'namedStyleType': 'NORMAL_TEXT'}, 'fields': 'namedStyleType'}},
        {'insertInlineImage': {'location': {'index': end}, 'uri': uri,
                               'objectSize': {'width': {'magnitude': width_pt, 'unit': 'PT'}}}},
    ]


def add_image(doc_id, after_para, data, content_type):
    """A picture the owner pasted on the screen, into the doc under the paragraph the cursor was in (11/20 本人「この
    読み上げページ（台本エディター）には画像も貼れるようにしたい」). Google reads the picture from Dan's public file link."""
    import uuid
    from PIL import Image
    from app.paths import LIVE_ROOT
    kind = (content_type or '').split(';')[0].strip().lower()
    if kind not in IMAGE_TYPES: raise ListenError('貼れるのは PNG・JPEG・GIF・WebP の画像です。')
    if not data or len(data) > 20_000_000: raise ListenError('画像が大きすぎます（20MBまで）。')
    try:
        im = Image.open(io.BytesIO(data)); im.load()
    except Exception:
        raise ListenError('画像を読めませんでした。')
    if kind == 'image/webp':                    # Docs takes PNG / JPEG / GIF only
        out = io.BytesIO(); im.save(out, 'PNG'); data = out.getvalue()
    name = f'script-image-{uuid.uuid4().hex}{IMAGE_TYPES[kind]}'
    folder = LIVE_ROOT / 'uploads'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    origin = os.environ.get('DAN_PUBLIC_ORIGIN') or 'https://dan.paina.info'
    width = max(60, min(PAGE_WIDTH_PT, round(im.width * 0.75)))
    _follow(doc_id)
    with _owner_lock:
        doc = fetch(doc_id)
        reqs = image_requests(doc, after_para, f'{origin}/api/v1/files/{name}', width)
        done = _docs('POST', f'{doc_id}:batchUpdate', doc['_account'],
                     body={'requests': reqs, 'writeControl': {'requiredRevisionId': doc['revisionId']}})
    _log_owner_action(doc_id, doc.get('title', ''), action='image', file=name, after_para=after_para)
    return {'changed': True, 'para': after_para + 1, 'file': f'/api/v1/files/{name}',
            'revision': (done.get('writeControl') or {}).get('requiredRevisionId')}


def image_delete_requests(doc, object_id):
    """Take a picture out; its paragraph goes too when the picture was all it held."""
    for el in doc.get('body', {}).get('content', []):
        p = el.get('paragraph')
        if not p: continue
        for e in p.get('elements', []):
            ioe = e.get('inlineObjectElement')
            if not ioe or ioe.get('inlineObjectId') != object_id: continue
            if ioe.get('suggestedInsertionIds') or ioe.get('suggestedDeletionIds'):
                raise ListenError('提案の画像は、提案の札で「承認」か「却下」を押してください。', 409)
            alone = all(x is e or ((x.get('textRun') or {}).get('content', '').strip() == '') for x in p['elements'])
            if alone and el['endIndex'] < doc['body']['content'][-1]['endIndex']:
                return [{'deleteContentRange': {'range': {'startIndex': el['startIndex'], 'endIndex': el['endIndex']}}}]
            return [{'deleteContentRange': {'range': {'startIndex': e['startIndex'], 'endIndex': e['endIndex']}}}]
    raise ListenError('その画像はもうドキュメントにありません。', 409)


def remove_image(doc_id, object_id):
    _follow(doc_id)
    with _owner_lock:
        doc = fetch(doc_id)
        reqs = image_delete_requests(doc, object_id)
        _docs('POST', f'{doc_id}:batchUpdate', doc['_account'],
              body={'requests': reqs, 'writeControl': {'requiredRevisionId': doc['revisionId']}})
    _log_owner_action(doc_id, doc.get('title', ''), action='image-delete', object=object_id)
    return {'changed': True}


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

@_retry_stale
def decide(doc_id, sid, accept, by_edit=False, log=True):
    """Accept or reject one suggestion the way Docs does. The Docs API has no accept/reject, so the same result is
    written: text that stays is deleted and written again as plain text with its style, text that goes is deleted.
    Tried on a copy 11/19: Docs then shows the suggestion as settled. The owner's own suggestions (kept by the
    screen) are written as a plain change, or dropped. ``by_edit``: the owner typed over its words."""
    if M.is_owner(sid): return _decide_owner(doc_id, sid, accept)
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
            ioe = e.get('inlineObjectElement')
            if ioe and (sid in (ioe.get('suggestedInsertionIds') or []) or sid in (ioe.get('suggestedDeletionIds') or [])):
                # A picture in the suggestion (Dan puts screenshots in as suggestions, 11/20): written again plainly
                # from its own picture link when it stays, taken out when it goes.
                kind = 'ins' if sid in (ioe.get('suggestedInsertionIds') or []) else 'del'
                emb = ((doc.get('inlineObjects') or {}).get(ioe.get('inlineObjectId'), {}).get('inlineObjectProperties') or {}).get('embeddedObject') or {}
                image = {'uri': (emb.get('imageProperties') or {}).get('contentUri'), 'size': emb.get('size')}
                if (kind == 'ins') == accept and not image['uri']:
                    raise ListenError('この提案の画像を読めませんでした。ドキュメントで決めてください。', 409)
                runs.append((e['startIndex'], e.get('endIndex', e['startIndex'] + 1), kind, '', {}, pstyle, nxt, image))
                continue
            if not r: continue
            ins, dele = r.get('suggestedInsertionIds') or [], r.get('suggestedDeletionIds') or []
            if sid not in ins and sid not in dele: continue
            kind = 'ins' if sid in ins else 'del'
            others = (set(ins) | set(dele)) - {sid}
            if others:
                # Overlapping suggestions (words one adds, another takes out). Rejecting the adding one takes all its
                # words out, inner suggestions with them; taking it takes the inner taking-out too; taking out words
                # that another adds just takes them out. Anything else cannot be written as Docs would keep it.
                if kind == 'ins' and not accept: pass
                elif kind == 'ins' and not (set(ins) - {sid}) and dele: kind = 'del'
                elif kind == 'del' and accept: pass
                else: raise ListenError('この提案は別の提案と重なっているので、ドキュメントで決めてください。', 409)
            end = e.get('endIndex', e['startIndex'] + sum(_units16(c) for c in r['content']))
            runs.append((e['startIndex'], end, kind, r['content'], r.get('textStyle') or {}, pstyle, nxt))
    if not runs:
        raise ListenError('この提案はもうありません。ドキュメントの方で決められたかもしれません。', 409)
    text_reqs, style_reqs = decide_requests(runs, accept, body_end)
    _docs('POST', f'{doc_id}:batchUpdate', doc['_account'],
          body={'requests': text_reqs, 'writeControl': {'requiredRevisionId': doc['revisionId']}})
    if style_reqs:
        _docs('POST', f'{doc_id}:batchUpdate', doc['_account'], body={'requests': style_reqs})
    added = ''.join(r[3] or '' for r in runs if r[2] == 'ins').strip()
    removed = ''.join(r[3] for r in runs if r[2] == 'del').strip()
    if log:
        _log_owner_action(doc_id, doc.get('title', ''), action='accept' if accept else 'reject', suggestion=sid,
                          added=added, removed=removed, **({'by_edit': True} if by_edit else {}))
    return {'done': True, 'added': added, 'removed': removed}


@_retry_stale
def _decide_owner(doc_id, sid, accept):
    _follow(doc_id)
    with _owner_lock:
        doc = fetch(doc_id)
        shown, sugs, placed = view(doc_id, doc)
        p = placed.get(sid)
        if p is None:
            if any(s['id'] == sid for s in sugs):
                M.save(OWNER_SUGS, doc_id, [s for s in sugs if s['id'] != sid])
            raise ListenError('この提案の所の文がドキュメントの方で変わっていたので、提案を外しました。', 409)
        toks, end = M.tokens(shown, p, p, _chars)
        new_toks, _ = M.plan(toks, M.text_of(toks), M.bmask_of(toks), 'edit', force={sid: accept})
        _write(doc_id, doc, sugs, placed, p, p, toks, end, new_toks, 'edit', log=False)
        title = doc.get('title', '')
        mine = next(s for s in sugs if s['id'] == sid)
        if accept:
            # The owner's own words: an edit for the learning, with the words around it.
            _log_owner_edit(doc_id, title, mine['pre'] + mine['del'] + mine['post'], mine['pre'] + mine['ins'] + mine['post'])
        extra = {}
        if mine.get('from'): extra['revised_from'] = mine['from']
        if mine.get('by'): extra['by_whom'] = mine['by']
        _log_owner_action(doc_id, title, action='settle', suggestion=sid, accept=accept, **extra)
    return {'done': True}


def _dan_stretches(shown, pi, sids):
    """Paragraph ``pi`` of ``shown`` as characters, with the stretches of Dan's suggested words in it: (tokens, chars,
    [(i, j, taken)]) where ``taken`` = the stretch has words of ``sids``. Suggestions that overlap (one of his inside
    another, 11/21 「そして2つ目です」 = 「2」 suggested for 「5」 inside a suggested paragraph) are one stretch."""
    got = M.tokens(shown, pi, pi, _chars)
    if not got: return None
    toks = got[0]
    chars = _chars(shown['body']['content'][pi]['paragraph'])
    dan = lambda c: {x for x in (*c[2]['ins'], *c[2]['del']) if not M.is_owner(x)}
    out, i = [], 0
    while i < len(chars):
        if not dan(chars[i]): i += 1; continue
        j, ids = i, set()
        while j < len(chars) and dan(chars[j]): ids |= dan(chars[j]); j += 1
        out.append((i, j, bool(ids & set(sids))))
        i = j
    return toks, chars, out


def _dan_ins(c):
    return any(not M.is_owner(x) for x in c[2]['ins'])


def _dan_del(c):
    return any(not M.is_owner(x) for x in c[2]['del'])


def _words_after(toks, chars, stretches):
    """Whether each character is in the doc once the taken stretches are taken back (their added words go, their struck
    words stay; the owner's added words are not in the doc)."""
    keep = [t['k'] != 'i' for t in toks]
    for i, j, taken in stretches:
        if taken:
            for k in range(i, j): keep[k] = not _dan_ins(chars[k])
    return keep


def adopt_plan(shown, sids, now='', paras=None):
    """Dan's suggestions ``sids`` as the owner's suggestions, read from the doc laid over with the owner's (``shown``):
    one per stretch of his suggested words, the words as they read without it (struck) and with it (added), with the
    words around it as they read once it is taken back in the doc. ``paras``: only these paragraphs (the ones being
    written). A paragraph end of his suggestion is not a word: it stays his suggestion in the doc (11/21 本人「提案モード
    の文章を編集できない」— most of Dan's suggestions add whole paragraphs, and those were refused). Returns (pieces, the
    doc positions of the characters to take back)."""
    import uuid
    content = shown.get('body', {}).get('content', [])
    out, positions = [], set()
    for pi, el in enumerate(content):
        if el.get('paragraph') is None or (paras is not None and pi not in paras): continue
        got = _dan_stretches(shown, pi, sids)
        if not got: continue
        toks, chars, stretches = got
        keep = _words_after(toks, chars, stretches)
        for i, j, taken in stretches:
            if not taken: continue
            positions |= {chars[k][0] for k in range(i, j)}
            pre = ''.join(t['ch'] for k, t in enumerate(toks[:i]) if keep[k])
            post = ''.join(t['ch'] for k, t in enumerate(toks[j:], j) if keep[k])
            dele = ''.join(toks[k]['ch'] for k in range(i, j) if not _dan_ins(chars[k]))
            ins = [toks[k] for k in range(i, j) if not _dan_del(chars[k])]
            ins_text = ''.join(t['ch'] for t in ins)
            if dele == ins_text: continue              # nothing left to suggest (words added and struck again)
            ids = sorted({x for k in range(i, j) for x in (*chars[k][2]['ins'], *chars[k][2]['del']) if not M.is_owner(x)})
            first = next((x for k in range(i, j) for x in (*chars[k][2]['ins'], *chars[k][2]['del']) if x in sids), ids[0])
            frm = {'by': 'dan', 'suggestion': first, 'del': dele, 'ins': ins_text}
            if len(ids) > 1: frm['suggestions'] = ids
            piece = {'id': M.OWNER + uuid.uuid4().hex[:12], 'para': pi, 'pre': pre[-M.CONTEXT:], 'del': dele,
                     'ins': ins_text, 'bm': ''.join('1' if t['b'] else '0' for t in ins),
                     'post': post[:M.CONTEXT], 'at': now, 'from': frm}
            if not pre and not post and not dele:
                piece.update(_above(shown, pi, sids, paras))
            out.append(piece)
    return out, positions


def adopt_pieces(shown, sids, now='', paras=None):
    return adopt_plan(shown, sids, now, paras)[0]


def _above(shown, pi, sids, paras):
    """For words that will be a whole paragraph of their own: the end of the nearest paragraph above that keeps words
    in the doc, and how many empty ones are between (script_listen_marks.overlay finds the place by it)."""
    for gap, pj in enumerate(range(pi - 1, -1, -1)):
        got = _dan_stretches(shown, pj, sids if (paras is None or pj in paras) else ())
        if not got: return {}
        toks, chars, stretches = got
        keep = _words_after(toks, chars, stretches)
        words = ''.join(t['ch'] for k, t in enumerate(toks) if keep[k])
        if words: return {'above': words[-M.CONTEXT:], 'gap': gap}
    return {}


def take_back_requests(doc, positions, paras):
    """Docs API requests that take back Dan's suggested words at doc ``positions`` in paragraphs ``paras``: added words
    go, struck words are written again plainly. Not the paragraph ends (those stay his suggestion, so the paragraphs
    stay where they are and 却下 still takes them out). Returns (text requests, style requests)."""
    content = doc.get('body', {}).get('content', [])
    body_end = content[-1].get('endIndex') if content else None
    runs = []
    for pi in paras:
        if not (0 <= pi < len(content)) or not content[pi].get('paragraph'): continue
        pstyle = (content[pi]['paragraph'].get('paragraphStyle') or {}).get('namedStyleType', 'NORMAL_TEXT')
        for e in content[pi]['paragraph'].get('elements', []):
            r = e.get('textRun')
            if not r or e['startIndex'] not in positions: continue
            ins = [x for x in (r.get('suggestedInsertionIds') or []) if not M.is_owner(x)]
            text = r['content']
            end = e.get('endIndex', e['startIndex'] + sum(_units16(c) for c in text))
            while text.endswith('\n'):        # the paragraph end stays his
                text, end = text[:-1], end - 1
            if not text: continue
            runs.append((e['startIndex'], end, 'ins' if ins else 'del', text, r.get('textStyle') or {}, pstyle, None))
    if not runs: return [], []
    return decide_requests(runs, False, body_end)


def _adopt(doc_id, doc, shown, sugs, sids, paras=None):
    """Take Dan's suggestions ``sids`` back in the doc and keep the same words as the owner's suggestions, so the
    owner can go on writing them as suggestions (11/21). Only in ``paras`` (the paragraphs being written): the rest of
    a suggestion that goes over several paragraphs stays his. The doc then no longer shows those words in Google
    Docs; the screen does, and 承認 writes them like the owner's own."""
    now = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    paras = set(paras) if paras is not None else None
    pieces, positions = adopt_plan(shown, set(sids), now, paras)
    if not positions: raise ListenError(GONE_HERE, 409)
    if paras is None:
        paras = set(range(len(shown.get('body', {}).get('content', []))))
    text_reqs, style_reqs = take_back_requests(doc, positions, sorted(paras))
    if text_reqs:
        _docs('POST', f'{doc_id}:batchUpdate', doc['_account'],
              body={'requests': text_reqs, 'writeControl': {'requiredRevisionId': doc['revisionId']}})
    if style_reqs:
        _docs('POST', f'{doc_id}:batchUpdate', doc['_account'], body={'requests': style_reqs})
    M.save(OWNER_SUGS, doc_id, list(sugs) + pieces)
    for piece in pieces:
        _log_owner_action(doc_id, doc.get('title', ''), action='adopt', suggestion=piece['id'], dan_suggestion=piece['from']['suggestion'],
                          before=piece['pre'] + piece['del'] + piece['post'], after=piece['pre'] + piece['ins'] + piece['post'],
                          revised_from=piece['from'])


def accept_all(doc_id):
    return decide_all(doc_id, True)


def reject_all(doc_id):
    """Every suggestion in the doc taken back (11/20 本人「全却下ボタンも作って」)."""
    r = decide_all(doc_id, False)
    return {'rejected': r['accepted'], 'failed': r['failed']}


def decide_all(doc_id, accept):
    """Every suggestion in the doc accepted (or rejected), the owner's own first (they are found by the words around
    them), then the doc's. Ones that cannot be (overlapping another) are left and counted."""
    done = failed = 0
    _, sugs, placed = view(doc_id)
    for sid in sorted(placed, key=lambda x: placed[x]):
        try: _decide_owner(doc_id, sid, accept); done += 1
        except ListenError: failed += 1
    # The doc's: all in one write. Taking every suggestion is clear even where they overlap (words one suggestion adds
    # and another takes out): a letter any of them takes out goes, the rest stays as plain text. Taking every one back
    # likewise: a letter any of them adds goes, the rest stays.
    doc = fetch(doc_id)
    content = doc.get('body', {}).get('content', [])
    body_end = content[-1].get('endIndex') if content else None
    runs, ids = [], {}
    paras = [el for el in content if el.get('paragraph')]
    for k, el in enumerate(paras):
        p = el['paragraph']
        pstyle = (p.get('paragraphStyle') or {}).get('namedStyleType', 'NORMAL_TEXT')
        nxt = (paras[k + 1]['paragraph'].get('paragraphStyle') or {}).get('namedStyleType', 'NORMAL_TEXT') if k + 1 < len(paras) else None
        for e in p.get('elements', []):
            r = e.get('textRun')
            ioe = e.get('inlineObjectElement')
            if ioe and (ioe.get('suggestedInsertionIds') or ioe.get('suggestedDeletionIds')):
                # A suggested picture (Dan's screenshots, 11/20): an added one written again plainly from its own
                # picture link, a removed one taken out. (Copied from decide() with its sid/accept, it raised
                # NameError and the button gave 500 on any doc with a suggested picture, 11/20.)
                kind = 'del' if ioe.get('suggestedDeletionIds') else 'ins'
                emb = ((doc.get('inlineObjects') or {}).get(ioe.get('inlineObjectId'), {}).get('inlineObjectProperties') or {}).get('embeddedObject') or {}
                image = {'uri': (emb.get('imageProperties') or {}).get('contentUri'), 'size': emb.get('size')}
                if (kind == 'ins') == accept and not image['uri']:
                    raise ListenError('提案の画像を読めませんでした。画像の提案はドキュメントで決めてください。', 409)
                runs.append((e['startIndex'], e.get('endIndex', e['startIndex'] + 1), kind, '', {}, pstyle, nxt, image))
                for sid in ioe.get('suggestedDeletionIds' if kind == 'del' else 'suggestedInsertionIds') or []:
                    ids.setdefault(sid, {'added': '', 'removed': ''})['added' if kind == 'ins' else 'removed'] += '[画像]'
                continue
            if not r: continue
            ins, dele = r.get('suggestedInsertionIds') or [], r.get('suggestedDeletionIds') or []
            if not ins and not dele: continue
            end = e.get('endIndex', e['startIndex'] + sum(_units16(c) for c in r['content']))
            kind = ('del' if dele else 'ins') if accept else ('ins' if ins else 'del')
            runs.append((e['startIndex'], end, kind, r['content'], r.get('textStyle') or {}, pstyle, nxt))
            for sid in ins: ids.setdefault(sid, {'added': '', 'removed': ''})['added'] += r['content']
            for sid in dele: ids.setdefault(sid, {'added': '', 'removed': ''})['removed'] += r['content']
    if runs:
        text_reqs, style_reqs = decide_requests(runs, accept, body_end)
        _docs('POST', f'{doc_id}:batchUpdate', doc['_account'],
              body={'requests': text_reqs, 'writeControl': {'requiredRevisionId': doc['revisionId']}})
        if style_reqs:
            _docs('POST', f'{doc_id}:batchUpdate', doc['_account'], body={'requests': style_reqs})
        for sid, w in ids.items():
            _log_owner_action(doc_id, doc.get('title', ''), action='accept' if accept else 'reject', suggestion=sid, added=w['added'].strip(),
                              removed=w['removed'].strip(), all_at_once=True)
            done += 1
    return {'accepted': done, 'failed': failed}


def decide_requests(runs, accept, body_end=None):
    """runs: (start, end, 'ins'|'del', text, textStyle, paragraph style, next paragraph's style) of one suggestion.
    Returns (text requests, style requests). The styles go in a second write at the final positions: written in the
    same write, text put back next to the suggestion's other runs still counted as suggested and lost its bold (11/19)."""
    text_reqs, kept = [], []
    for start, end, kind, text, style, pstyle, nxt, *more in sorted(runs, key=lambda r: r[0], reverse=True):
        image = more[0] if more else None
        if image is not None:                     # a picture: out, and in again plainly when it stays
            text_reqs.append({'deleteContentRange': {'range': {'startIndex': start, 'endIndex': end}}})
            if (kind == 'ins') == accept:
                put = {'location': {'index': start}, 'uri': image['uri']}
                if image.get('size'): put['objectSize'] = image['size']
                text_reqs.append({'insertInlineImage': put})
            continue
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
OWNER_SUGS = STATE / 'owner_suggestions.json'
_owner_lock = threading.RLock()
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


def anchor_start(a):
    return a.get('start') if isinstance(a, dict) else a


def _suggestion_words(sug):
    ins, dele = (sug.get('ins') or '').strip(), (sug.get('del') or '').strip()
    if ins and dele: return f"置き換え「{dele}」→「{ins}」"
    if ins: return f"足す「{ins}」"
    return f"消す「{dele}」"


def anchor_note(comment_ids):
    """For Dan's answer: the sentence each comment made on the listening screen was written on, and the suggestion
    it is about when the owner wrote it on a suggestion's card (11/20 本人「提案に対して『それおかしいから、もう少し
    こういう風に直して』と言いたい」)."""
    anchors = _anchors()
    lines, about = [], []
    for cid in comment_ids:
        a = anchors.get(cid)
        if not isinstance(a, dict): continue
        if a.get('sentence'): lines.append(f"{cid}: 文「{a['sentence']}」")
        if isinstance(a.get('suggestion'), dict):
            sug = a['suggestion']
            # The owner's own suggestion is kept by the screen (the Docs API cannot write one): Dan cannot see it in
            # the doc and does not decide it.
            who = '本人が台本を聞く画面の提案モードで書いた提案（ドキュメントには入っていないのでブラウザでは見えない。決めるのは本人）' if M.is_owner(sug.get('id')) else '提案'
            about.append(f"{cid}: {who}（{_suggestion_words(sug)}）")
    out = []
    if lines:
        out.append('台本を聞く画面から書かれたコメントの場所（Googleでは本文の位置が残らないので、ここで分かる）。'
                   'quote はその文の中で本人が選んだ言葉:\n' + '\n'.join(lines))
    if about:
        out.append('次のコメントは、本人が本文の提案（ドキュメントの提案モードの直し）の札に書いたもの。コメントはその提案への'
                   '意見や直しの頼み:\n' + '\n'.join(about) + '\n'
                   'その提案を直す時は、ダンが出した提案なら、ブラウザでその提案を却下してから、直した提案を同じ所に入れ直す'
                   '（古い提案と新しい提案を両方残さない）。返事は同じコメントのスレッドに書く。ダン以外が出した提案は承認も却下もせず、'
                   '返事で本人に確かめる。')
    return '\n'.join(out)


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
        a = anchors.get(t['id'])
        sug = a.get('suggestion') if isinstance(a, dict) and isinstance(a.get('suggestion'), dict) else None
        out.append({'id': t['id'], 'quote': quote, 'resolved': bool(t.get('resolved')), 'messages': msgs,
                    'at': t.get('createdTime'), 'working': busy.get(t['id']), 'start': anchor_start(a),
                    'suggestion': sug.get('id') if sug else None,
                    # Its words, so the screen can tell which suggestion Dan put in for it once it is gone (11/20).
                    'suggestion_words': {'ins': sug.get('ins') or '', 'del': sug.get('del') or ''} if sug else None})
    out.sort(key=lambda x: x['at'] or '')
    return {'threads': out, 'can_comment': private}


# How long a finished answer stays on the screen's work monitor (11/20 本人「プロセスモニターも付けたい」).
DONE_SHOWN = 15 * 60
_JOB_KINDS = {'progress', 'result', 'error', 'tool', 'input'}


def _ts(value):
    from datetime import datetime
    try: return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except Exception: return 0.0


_JP = re.compile(r'[\u3040-\u30ff\u4e00-\u9fff]')
_TOOL_SAYS = (
    (('script_learning.py before',), '直す前の本文を記録しています'),
    (('script_learning.py after',), '直した後の本文を記録しています'),
    (('gdoc_comments.py reply', 'confirm-export-reply'), 'コメントに返事を書いています'),
    (('talk-script', 'SKILL.md', 'revision.md'), '台本の直し方の手順を読んでいます'),
    (('ブラウザ', 'browser', '要素 @', 'クリック'), 'ドキュメントの画面で作業しています'),
    (('ファイル読み取り',), '資料を読んでいます'),
)


def _tool_says(label):
    """A tool step in plain words, for the monitor's one line when Dan has not written a line for a while."""
    for keys, words in _TOOL_SAYS:
        if any(k in label for k in keys): return words
    return '調べています'


TOUCH_AFTER = 3   # seconds a sentence stays lit after the step that touched it ended (the screen reads every 2.5 s)


def _touching(state, now):
    """The words Dan's browser is selecting or typing in the doc right now (mcp_server._touch_words), or did in the
    last few seconds. None while he reads, thinks or writes his answer: nothing is lit then (11/20 本人「考えているだけで
    操作していない時は光るべきじゃない」)."""
    cur = state.get('current_tool') or {}
    if cur.get('touch'): return {'words': cur['touch'], 'live': True}
    last = state.get('last_tool') or {}
    if last.get('touch') and now - _ts(last.get('at')) <= TOUCH_AFTER: return {'words': last['touch'], 'live': False}
    return None


def activity(doc_id):
    """What Dan is doing on the doc's comments now: one entry per answer (batch) that is waiting, working or ended
    in the last DONE_SHOWN seconds, with the comments it is about and its work log (the same lines as the chat's)."""
    from app.services import gdoc_events as E
    with E.db() as c:
        rows = c.execute("SELECT id,payload,status,created,result FROM batches WHERE file_id=? ORDER BY created DESC LIMIT 12",
                         (doc_id,)).fetchall()
    now = time.time()
    jobs = []
    for r in rows:
        try: state = json.loads((E.ROOT / 'jobs' / f"{r['id']}.json").read_text())
        except Exception: state = {}
        live = r['status'] in ('pending', 'running', 'needs_room')
        ended = _ts(state.get('updated_at') or r['created'])
        if not live and now - ended > DONE_SHOWN: continue
        try: ids = [x['comment_id'] for x in json.loads(r['payload'])]
        except Exception: ids = []
        events = []
        results = {(e.get('text') or '').strip() for e in state.get('events') or [] if e.get('kind') == 'result'}
        for e in state.get('events') or []:
            if e.get('kind') not in _JOB_KINDS: continue
            # The answer, once: the step line before it is the same words, cut short.
            head = (e.get('text') or '').strip()[:200]
            if e['kind'] == 'progress' and head and any(r.startswith(head) for r in results): continue
            text = (e.get('label') if e.get('kind') == 'tool' and e.get('label') else e.get('text')) or ''
            # The text Dan writes between steps is sometimes an English note to himself: not a line for the owner.
            if e['kind'] == 'progress' and len(_JP.findall(text)) * 2 < len(re.findall(r'[A-Za-z]', text)): continue
            item = {'seq': e.get('seq'), 'kind': e['kind'], 'text': text[:4000], 'at': e.get('at')}
            if e['kind'] == 'tool':
                item['say'] = _tool_says(text)
                item['text'] = text.strip().splitlines()[0][:160] if text.strip() else ''
            events.append(item)
        # The batch row says if the answer really landed (a fluent reply without a Docs reply is needs_attention).
        status = r['status'] if r['status'] in ('pending', 'running', 'needs_room') else (
            'completed' if r['status'] == 'completed' else 'failed' if r['status'] in ('failed', 'cancelled') else 'attention')
        if status == 'running' and state.get('state') in ('queued', 'pending', None) and not events: status = 'pending'
        jobs.append({'id': r['id'], 'status': status, 'comment_ids': ids, 'started': state.get('created_at') or r['created'],
                     'updated': state.get('updated_at'), 'events': events[-200:],
                     'touch': _touching(state, now) if status == 'running' else None})
    # The one working now first, then the ones waiting their turn (oldest first), then the ended ones (newest first).
    rank = {'running': 0, 'needs_room': 1, 'pending': 2}
    jobs.sort(key=lambda j: (rank.get(j['status'], 3), _ts(j['started']) if j['status'] in rank else -_ts(j['started'])))
    return {'jobs': jobs}


def _owner_words(text):
    text = (text or '').strip()
    if not text: raise ListenError('空のままでは送れません。')
    if text.startswith(('ダン：', 'ダン:', '【変えた所】', '【根拠】')):
        raise ListenError('「ダン：」で始まる文はダンの返事と見分けられないので、別の書き出しにしてください。')
    return text


def _clean_suggestion(sug):
    if not isinstance(sug, dict) or not sug.get('id'): return None
    return {'id': str(sug['id'])[:200], 'ins': str(sug.get('ins') or '')[:2000], 'del': str(sug.get('del') or '')[:2000]}


def _remember_anchor(cid, **fields):
    STATE.mkdir(parents=True, exist_ok=True)
    anchors = _anchors()
    a = anchors.get(cid) if isinstance(anchors.get(cid), dict) else {}
    a.update({k: v for k, v in fields.items() if v is not None})
    anchors[cid] = a
    ANCHORS.write_text(json.dumps(anchors, ensure_ascii=False))


def add_comment(doc_id, quote, text, start=None, sentence='', suggestion=None):
    from app.services import gdoc_drive as G
    text = _owner_words(text)
    if not owner_only(doc_id) or not ensure_watched(doc_id):
        raise ListenError('お客さんも開けるドキュメントなので、ここからはコメントできません（ダンの返事がお客さんにも見えるため）。'
                          '作業用の台本で書いてください。', 403)
    body = {'content': text}
    quote = (quote or '').strip()
    if quote: body['quotedFileContent'] = {'mimeType': 'text/html', 'value': quote}
    made = G.request(_account(doc_id), 'POST', f'files/{doc_id}/comments', body, {'fields': 'id'})
    # Where it was written. Docs keeps no place for a comment made through the API, so Dan's answer reads the sentence
    # from here (gdoc_events.prompt): 11/19 a comment on 「行動力」 could have meant any of ten sentences.
    _remember_anchor(made['id'], start=start, sentence=(sentence or '').strip()[:600], doc_id=doc_id,
                     suggestion=_clean_suggestion(suggestion))
    _poke(doc_id)
    return {'id': made['id']}


def reply(doc_id, comment_id, text, suggestion=None):
    from app.services import gdoc_drive as G
    text = _owner_words(text)
    if not owner_only(doc_id) or not ensure_watched(doc_id):
        raise ListenError('お客さんも開けるドキュメントなので、ここからは返事を書けません。', 403)
    made = G.request(_account(doc_id), 'POST', f'files/{doc_id}/comments/{comment_id}/replies', {'content': text}, {'fields': 'id'})
    # A reply on a suggestion's card: the thread is now about that suggestion (Dan may have put in a new one).
    sug = _clean_suggestion(suggestion)
    if sug: _remember_anchor(comment_id, doc_id=doc_id, suggestion=sug)
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
