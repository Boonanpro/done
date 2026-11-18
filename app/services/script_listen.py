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
        flags = {'del': bool(run.get('suggestedDeletionIds')), 'ins': bool(run.get('suggestedInsertionIds')),
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


def outline(doc):
    """The doc cut into what the screen shows: headings, notes and sentences. Only sentences are spoken."""
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
        if not text: continue
        if style == 'TITLE' or style == 'HEADING_1':
            units.append({'kind': 'title', 'text': text}); continue
        if text.startswith('◎'):
            if text.startswith(SCRIPT_HEADING): mode = 'script'
            elif any(text.startswith(h) for h in SKIP_HEADINGS): mode = 'before' if seen_script else 'skip'
            elif mode == 'script':
                # A ◎ line inside the script (◎追加特典① …) is a small heading of the script, not a new top part.
                # As a top-level heading the screen filed everything after it under 「読みません」 (11/18).
                section = text
                units.append({'kind': 'heading', 'level': 3, 'text': text, 'read': True}); continue
            units.append({'kind': 'heading', 'level': 1, 'text': text, 'read': mode == 'script'}); continue
        if mode != 'script':
            units.append({'kind': 'note', 'text': text, 'section': 'top'}); continue
        if style in ('HEADING_2', 'HEADING_3') or re.match(r'^【\d+】', text) or text.startswith('▼'):
            level = 2 if (style == 'HEADING_2' or text.startswith('【')) else 3
            section = text
            units.append({'kind': 'heading', 'level': level, 'text': text, 'read': True}); continue
        visible = [c for c in chars if not c[2]['del']]
        if all(c[2]['blue'] or not c[1].strip() for c in visible) or text.startswith('［'):
            units.append({'kind': 'note', 'text': text}); continue
        for part in _split(chars):
            while part and not part[0][1].strip(): part = part[1:]
            while part and not part[-1][1].strip(): part = part[:-1]
            if not part: continue
            speak = _speakable(part)
            if not speak or not re.search(r'[\w぀-ヿ一-鿿]', speak):
                units.append({'kind': 'note', 'text': _raw(part).strip()}); continue
            start = part[0][0]
            end = part[-1][0] + _units16(part[-1][1])
            inside = [c for c in chars if start <= c[0] < end]
            units.append({'kind': 'say', 'text': _raw(part).strip(), 'speak': speak, 'para': pi, 'start': start, 'end': end,
                          'bmask': ''.join('1' if c[2]['bold'] else '0' for c in part),
                          'bold': all(c[2]['bold'] for c in part if c[1].strip()),
                          'locked': any(c[2]['ins'] or c[2]['del'] for c in inside), 'section': section, 'gap': 's'})
    # Longer pause where a paragraph or a section ends.
    says = [i for i, u in enumerate(units) if u['kind'] == 'say']
    for n, i in enumerate(says):
        nxt = says[n + 1] if n + 1 < len(says) else None
        if nxt is None: units[i]['gap'] = 'h'
        elif any(units[k]['kind'] == 'heading' for k in range(i + 1, nxt)): units[i]['gap'] = 'h'
        elif units[nxt].get('para') != units[i].get('para'): units[i]['gap'] = 'p'
    return units


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
    return {'doc_id': doc_id, 'title': title, 'revision': doc.get('revisionId'), 'version': doc.get('revisionId'),
            'voice': voice, 'voices': [{'id': v['id'], 'name': v['name']} for v in VOICES], 'units': units}


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
    # The doc shows these edits under Dan's Google account; this file keeps that they were the owner's words.
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'owner_edits.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'doc_id': doc_id, 'title': title,
                            'before': old, 'after': new, 'by': 'owner', 'via': 'script-listen'}, ensure_ascii=False) + '\n')


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
