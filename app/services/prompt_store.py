"""The instructions that run Dan, kept as text files the owner can read and rewrite (owner, 2026-11-17).

Why: each time the owner pointed at a fault, Dan added a sentence somewhere inside the Python code, and the owner could
not see what had piled up (「修正指示を出せば出すほど仕組みがおかしくなっていく」). The owner cannot read code but can read and
rewrite Japanese, so the sentences the models read live as Markdown files in ~/.dan/workspace/prompts/ (next to RULES.md
and SOUL.md), and the screen /prompts shows each one where it works in Dan, with its history.

One road for every change: the code reads only these files (at each use, so a saved change works from the next call
without a restart); the screen saves through save(); Dan saves through scripts/prompts.py or by editing the file, and an
edit made outside save() is recorded as Dan's the next time the file is read. Every version stays in
prompts/.history/<id>.jsonl, so any version can be put back.

app/prompts/seed/ holds the text as it was when moved out of the code. It is used only when a file is missing (a fresh
machine); changing a seed changes nothing on a machine that already has its files.

Kinds (app/prompts/catalog.json):
- text: the file is the text, without the newlines around it (the code adds those, so a textarea cannot lose them).
- sections: `## key` lines, each followed by its text; the code needs every key (a route name, an option).
- words: one phrase per line, joined into a pattern by the code.
"""
import fcntl
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SEED = REPO / 'app' / 'prompts' / 'seed'
CATALOG = REPO / 'app' / 'prompts' / 'catalog.json'
WORKSPACE = Path.home() / '.dan' / 'workspace'
_lock = threading.RLock()
_cache: dict[str, tuple] = {}    # id -> ((path, mtime_ns, size), text)
SECTION = re.compile(r'^##\s+(\S+)\s*$', re.M)
WHO = {'owner': 'みきさん', 'dan': 'ダン', 'seed': 'プログラムから移した元の文'}


def root():
    return Path(os.environ.get('DAN_PROMPTS_DIR') or WORKSPACE / 'prompts')


def catalog():
    return json.loads(CATALOG.read_text(encoding='utf-8'))


def entry(prompt_id):
    for item in catalog()['prompts']:
        if item['id'] == prompt_id:
            return item
    raise KeyError(prompt_id)


def path_of(prompt_id):
    """The file of a prompt. Workspace files that were already files (RULES.md…) keep their own place."""
    item = entry(prompt_id)
    if item.get('workspace_file'):
        base = Path(os.environ.get('DAN_PROMPTS_WORKSPACE') or WORKSPACE)
        return base / item['workspace_file']
    if item.get('readonly'):
        return REPO / item['source_file']
    return root() / f'{prompt_id}.md'


def _history_path(prompt_id):
    return root() / '.history' / (prompt_id.replace('/', '__') + '.jsonl')


def sha(text):
    return hashlib.sha1(text.encode('utf-8')).hexdigest()[:12]


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _clean(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')


def _read_history(prompt_id):
    path = _history_path(prompt_id)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try: out.append(json.loads(line))
        except ValueError: continue
    return out


def _append(prompt_id, record, check_sha=None):
    """Append a version under a file lock; with check_sha, only when the last recorded version differs from it
    (two processes reading the same new file record it once)."""
    path = _history_path(prompt_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a+', encoding='utf-8') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            if check_sha is not None:
                f.seek(0)
                last = None
                for line in f.read().splitlines():
                    try: last = json.loads(line)
                    except ValueError: pass
                if last and last.get('sha') == check_sha:
                    return False
            f.seek(0, os.SEEK_END)
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
            f.flush()
            return True
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _seed_text(prompt_id):
    source = entry(prompt_id).get('source_file')
    path = REPO / source if source else SEED / f'{prompt_id}.md'
    return path.read_text(encoding='utf-8').strip('\n')


def _ensure(prompt_id):
    path = path_of(prompt_id)
    item = entry(prompt_id)
    if not path.exists() and item.get('source_file') and not item.get('readonly'):
        return REPO / item['source_file']
    if not path.exists() and not item.get('workspace_file') and not item.get('readonly'):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(_seed_text(prompt_id) + '\n', encoding='utf-8')
        os.replace(tmp, path)
    return path


def _record_outside_edit(prompt_id, text, mtime):
    """A file that differs from its last recorded version was changed outside save(): Dan's edit (the owner edits on
    the screen). The first version of a moved prompt is the seed."""
    digest = sha(text)
    history = _read_history(prompt_id)
    if history and history[-1].get('sha') == digest:
        return
    item = entry(prompt_id)
    first = not history
    if first and not item.get('workspace_file') and text == _seed_text(prompt_id):
        record = {'at': _now(), 'by': 'seed', 'note': f"{item.get('source', 'プログラム')} から、中身を変えずに移した", 'sha': digest, 'text': text}
    elif first:
        record = {'at': datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec='seconds'), 'by': 'dan',
                  'note': 'この画面ができた時の文', 'sha': digest, 'text': text}
    else:
        record = {'at': datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec='seconds'), 'by': 'dan',
                  'note': '画面の外で直された（ダンが直接ファイルを直した）', 'sha': digest, 'text': text}
    _append(prompt_id, record, check_sha=digest)


def _code_value(item):
    """A sentence still inside the code, shown as it is (read only)."""
    import importlib
    value = getattr(importlib.import_module(item['module']), item['attr'])
    if callable(value): value = value()
    if isinstance(value, dict): return format_sections({k: v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        lines = []
        for tool in value:
            if isinstance(tool, dict):
                lines.append(f"## {tool.get('name', '')}\n{tool.get('description', '')}")
                for name, prop in ((tool.get('parameters') or {}).get('properties') or {}).items():
                    if isinstance(prop, dict) and prop.get('description'): lines.append(f"- {name}: {prop['description']}")
        return '\n'.join(lines)
    return str(value).strip('\n')


def text(prompt_id):
    """The prompt as the code uses it, read at each use (cached until the file changes)."""
    item = entry(prompt_id)
    if item.get('readonly') and item.get('module'):
        return _code_value(item)
    with _lock:
        path = _ensure(prompt_id)
        st = path.stat()
        stamp = (path, st.st_mtime_ns, st.st_size)
        cached = _cache.get(prompt_id)
        if cached and cached[0] == stamp:
            return cached[1]
        raw = _clean(path.read_text(encoding='utf-8'))
        value = raw if entry(prompt_id).get('workspace_file') or entry(prompt_id).get('readonly') else raw.strip('\n')
        if not entry(prompt_id).get('readonly'):
            try: _record_outside_edit(prompt_id, value, st.st_mtime)
            except OSError: pass
        _cache[prompt_id] = (stamp, value)
        return value


def parse_sections(value):
    """{key: text} from `## key` lines, in order."""
    marks = list(SECTION.finditer(value))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(value)
        out[m.group(1)] = value[m.end():end].strip('\n')
    return out


def sections(prompt_id):
    return parse_sections(text(prompt_id))


def format_sections(values):
    return '\n\n'.join(f'## {k}\n{v}' for k, v in values.items())


def parse_words(value):
    return [w.strip() for w in value.split('\n') if w.strip()]


def words(prompt_id):
    return parse_words(text(prompt_id))


def fill(prompt_id, **values):
    """A template with {name} marks filled by plain replacement (other braces stay as they are)."""
    out = text(prompt_id)
    for k, v in values.items():
        out = out.replace('{' + k + '}', v)
    return out


def problems(prompt_id, value):
    """Why a new text cannot be used by the code (empty when it can)."""
    item = entry(prompt_id)
    if item.get('readonly'):
        return ['この文はまだプログラムの中にあるので、ここでは直せません。']
    if not value.strip():
        return ['空にはできません。']
    kind = item.get('kind', 'text')
    out = []
    if kind == 'sections':
        keys = list(parse_sections(value))
        need = item.get('keys') or []
        missing = [k for k in need if k not in keys]
        extra = [k for k in keys if need and k not in need]
        if missing: out.append('「## ' + '」「## '.join(missing) + '」の見出しが無くなっています。プログラムがこの見出しの名前で選ぶので、見出しの行は消さないでください。')
        if extra: out.append('「## ' + '」「## '.join(extra) + '」はプログラムが知らない見出しです。')
        if any(not v.strip() for v in parse_sections(value).values()): out.append('中身が空の見出しがあります。')
    if kind == 'words':
        bad = [w for w in parse_words(value) if '|' in w]
        if bad: out.append('言葉の中に「|」は使えません。')
        if not parse_words(value): out.append('言葉が1つもありません。')
    for mark in item.get('marks') or []:
        if '{' + mark + '}' not in value:
            out.append(f'「{{{mark}}}」が無くなっています。ここにプログラムが{(item.get("mark_notes") or {}).get(mark, "値")}を入れるので、残してください。')
    return out


def save(prompt_id, value, by='dan', note='', base_sha=None):
    """Write a new version and record it. base_sha: the version the editor started from; a different current version
    (changed meanwhile) refuses the save so nothing is lost."""
    value = _clean(value)
    item = entry(prompt_id)
    if not item.get('workspace_file'):
        value = value.strip('\n')
    found = problems(prompt_id, value)
    if found:
        raise ValueError(' '.join(found))
    with _lock:
        current = text(prompt_id)
        if base_sha and sha(current) != base_sha:
            raise RuntimeError('開いている間に、この文が別の所で直されました。開き直してから直してください。')
        if value == current:
            return {'saved': False, 'sha': sha(value)}
        path = path_of(prompt_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {'at': _now(), 'by': by if by in WHO else 'dan', 'note': note[:500], 'sha': sha(value), 'text': value}
        _append(prompt_id, record)
        tmp = path.with_name(path.name + '.saving')
        tmp.write_text(value + ('' if item.get('workspace_file') and value.endswith('\n') else '\n'), encoding='utf-8')
        os.replace(tmp, path)
        _cache.pop(prompt_id, None)
        text(prompt_id)
        return {'saved': True, 'sha': record['sha'], 'at': record['at']}


def history(prompt_id):
    """Versions, newest first."""
    if not entry(prompt_id).get('readonly'):
        text(prompt_id)
    return list(reversed(_read_history(prompt_id)))


def revert(prompt_id, version_sha, by='owner'):
    for record in _read_history(prompt_id):
        if record.get('sha') == version_sha:
            from zoneinfo import ZoneInfo
            when = datetime.fromisoformat(record['at']).astimezone(ZoneInfo('Asia/Tokyo')).strftime('%-m/%-d %H:%M')
            return save(prompt_id, record['text'], by=by, note=f'{when} の版（{WHO.get(record.get("by"), "")}）に戻した')
    raise KeyError(version_sha)


def summary(prompt_id):
    """What the list on the screen shows of one prompt."""
    item = entry(prompt_id)
    try: value = text(prompt_id)
    except (OSError, KeyError): value = ''
    last = None if item.get('readonly') else (_read_history(prompt_id) or [None])[-1]
    return {**item, 'chars': len(value), 'sha': sha(value),
            'last_by': (last or {}).get('by'), 'last_at': (last or {}).get('at'),
            'edited_by_owner': any(r.get('by') == 'owner' for r in _read_history(prompt_id)) if not item.get('readonly') else False}
