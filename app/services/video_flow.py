"""動画を編集する作業の図（指示文の画面の「動画の編集」。2026-11-23 本人「お前がこうやって直しても良い？って聞いて来ても
どこをどう変えようとしてるのかが分からないので、良し悪しの判断もできず承認も却下もできない」「あらゆる場面で何が起きているかを
ちゃんと理解したい」）。

- 段: app/prompts/video_flow.json。段ごとに読む手順書・案件の決まりの見出しと、使うプログラム。読む文は開くたびに今の版から抜き出す。
- 流し直す作業（runs）: ~/.dan/workspace/prompts/video-flow/runs/<id>.json。過去の1つの作業で、段ごとに何をしたか・出来たコマ。
- 直しの案（proposals）: ~/.dan/workspace/prompts/video-flow/proposals/<id>.json。「どの段の・どの文を・こう変える」と前後のコマ。
  本人が承認すると、文の直し（kind=text）はその場で手順書に保存される（by=owner）。作業の案（kind=work）は承認を記録し、
  画面がダンに「承認された」と伝える。
ダンが作業や案を足すのは scripts/video_flow.py だけ。
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.services import prompt_store

DEFS = Path(__file__).resolve().parents[1] / 'prompts' / 'video_flow.json'
UPLOADS = Path(__file__).resolve().parents[2] / 'uploads'
STATES = {'ok', 'bad', 'skipped', 'na'}
_lock = threading.Lock()
_HEAD = re.compile(r'^(#{1,6})\s', re.M)


def root() -> Path:
    return prompt_store.root() / 'video-flow'


def _now():
    return datetime.now(timezone.utc).isoformat()


def definitions() -> dict:
    return json.loads(DEFS.read_text(encoding='utf-8'))


def section(value: str, heading: str) -> str | None:
    """The part of a markdown text under a heading (the heading line starts with `heading`), up to the next heading of the
    same or a higher level. None when no such heading."""
    level = len(heading) - len(heading.lstrip('#'))
    for m in re.finditer(r'^' + re.escape(heading) + r'.*$', value, re.M):
        start = m.start()
        for n in _HEAD.finditer(value, m.end()):
            if len(n.group(1)) <= level:
                return value[start:n.start()].rstrip()
        return value[start:].rstrip()
    return None


def _title(prompt_id):
    try: return prompt_store.entry(prompt_id).get('title') or prompt_id
    except KeyError: return prompt_id


def cases() -> list[dict]:
    from app.services.skill_versions import skill_pages
    prefix = definitions()['case_prefix']
    return [{'id': p['id'][len(prefix):], 'title': p.get('title') or p['id']} for p in skill_pages() if p['id'].startswith(prefix)]


def _resolve(read: dict, case: str) -> dict:
    defs = definitions()
    pid = defs['case_prefix'] + case if read.get('case') else read['id']
    out = {'id': pid, 'title': _title(pid), 'heading': read.get('heading', ''), 'why': read.get('why', ''), 'case': bool(read.get('case'))}
    try:
        value = prompt_store.text(pid)
    except KeyError:
        return {**out, 'found': False, 'text': ''}
    if not read.get('heading'):
        return {**out, 'found': True, 'text': value, 'whole': True}
    part = section(value, read['heading'])
    return {**out, 'found': part is not None, 'text': part or ''}


def stages(case: str) -> list[dict]:
    out = []
    for st in definitions()['stages']:
        reads = [_resolve(r, case) for r in st.get('reads', [])]
        repo = Path(__file__).resolve().parents[2]
        programs = [{**p, 'exists': (repo / p['path']).exists()} for p in st.get('programs', [])]
        out.append({**st, 'reads': reads, 'programs': programs})
    return out


def _read_dir(kind: str) -> list[dict]:
    folder = root() / kind
    items = []
    for f in sorted(folder.glob('*.json')) if folder.exists() else []:
        try: items.append(json.loads(f.read_text(encoding='utf-8')))
        except (OSError, ValueError): continue
    items.sort(key=lambda x: x.get('at', ''), reverse=True)
    return items


def runs() -> list[dict]:
    return _read_dir('runs')


def proposals() -> list[dict]:
    out = _read_dir('proposals')
    for p in out:
        if p.get('kind', 'text') == 'text' and p.get('state') == 'pending':
            try: p['applies'] = prompt_store.text(p['prompt_id']).count(p.get('find', '')) == 1 if p.get('find') else False
            except KeyError: p['applies'] = False
    return out


def overview(case: str = '') -> dict:
    all_runs = runs()
    case = case or (all_runs[0].get('case') if all_runs else '') or 'suya-youtube'
    return {'case': case, 'cases': cases(), 'stages': stages(case), 'runs': all_runs, 'proposals': proposals()}


def _write(kind: str, item: dict) -> dict:
    folder = root() / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{item['id']}.json"
    tmp = path.with_suffix('.saving')
    tmp.write_text(json.dumps(item, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(path)
    return item


def _stage_ids():
    return {s['id'] for s in definitions()['stages']}


def frame(path: str) -> str:
    """Put a picture where the screen can show it (/api/v1/files/<name>) and return that address. Addresses pass through."""
    if path.startswith('/api/') or path.startswith('https://'):
        return path
    src = Path(path)
    if not src.is_file():
        raise ValueError(f'絵がありません: {path}')
    name = f'vflow_{uuid.uuid4().hex[:10]}{src.suffix.lower() or ".png"}'
    UPLOADS.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, UPLOADS / name)
    return f'/api/v1/files/{name}'


def _frames(values):
    return [{'src': frame(f['src']), 'time': str(f.get('time', '')), 'label': f.get('label', '')} for f in values or []]


def add_run(data: dict) -> dict:
    """One past piece of work, stage by stage: {title, case, work?:{url,thumb}, result?, stages:{<stage>:{state,did,frames?}}}."""
    known = _stage_ids()
    bad = set(data.get('stages', {})) - known
    if bad:
        raise ValueError(f'知らない段: {sorted(bad)}（段は {sorted(known)}）')
    st = {}
    for key, v in data.get('stages', {}).items():
        if v.get('state', 'ok') not in STATES:
            raise ValueError(f'state は {sorted(STATES)} のどれか')
        st[key] = {'state': v.get('state', 'ok'), 'did': v.get('did', ''), 'should': v.get('should', ''), 'frames': _frames(v.get('frames'))}
    item = {'id': data.get('id') or uuid.uuid4().hex[:12], 'at': data.get('at') or _now(), 'title': data['title'],
            'case': data.get('case', ''), 'work': data.get('work') or {}, 'result': data.get('result', ''),
            'owner': data.get('owner', ''), 'stages': st}
    with _lock:
        return _write('runs', item)


def propose(data: dict) -> dict:
    """{title, stage, kind: text|work, prompt_id?, find?, replace?, why, effect?, run?, before:{label,frames}, after:{label,frames}}."""
    if data.get('stage') not in _stage_ids():
        raise ValueError(f"段がありません: {data.get('stage')}")
    kind = data.get('kind', 'text')
    if kind not in ('text', 'work'):
        raise ValueError('kind は text か work')
    if kind == 'text':
        current = prompt_store.text(data['prompt_id'])   # KeyError: no such prompt
        if current.count(data.get('find', '')) != 1 or not data.get('find'):
            raise ValueError('find の文が、その指示文の中にちょうど1回ある必要があります')
    side = lambda v: {'label': (v or {}).get('label', ''), 'frames': _frames((v or {}).get('frames'))}
    item = {'id': data.get('id') or uuid.uuid4().hex[:12], 'at': _now(), 'title': data['title'], 'stage': data['stage'],
            'kind': kind, 'prompt_id': data.get('prompt_id', ''), 'find': data.get('find', ''), 'replace': data.get('replace', ''),
            'why': data.get('why', ''), 'effect': data.get('effect', ''), 'run': data.get('run', ''),
            'before': side(data.get('before')), 'after': side(data.get('after')), 'state': 'pending'}
    with _lock:
        return _write('proposals', item)


def decide(proposal_id: str, decision: str, note: str = '') -> dict:
    if decision not in ('approve', 'reject'):
        raise ValueError('approve か reject')
    path = root() / 'proposals' / f'{proposal_id}.json'
    with _lock:
        try: item = json.loads(path.read_text(encoding='utf-8'))
        except OSError: raise KeyError(proposal_id)
        if item.get('state') != 'pending':
            raise RuntimeError('この案はもう決まっています。')
        if decision == 'approve' and item.get('kind') == 'text':
            current = prompt_store.text(item['prompt_id'])
            if current.count(item['find']) != 1:
                raise RuntimeError('案を出した後に、この文が直されています。ダンに案を出し直してもらってください。')
            new = current.replace(item['find'], item['replace'], 1)
            if not item['replace']:
                new = re.sub(r'\n{3,}', '\n\n', new)
            saved = prompt_store.save(item['prompt_id'], new, 'owner', f"動画の編集の図で承認: {item['title']}", prompt_store.sha(current))
            item['saved_sha'] = saved.get('sha')
        item.update(state='approved' if decision == 'approve' else 'rejected', decided_at=_now(), note=note[:500])
        return _write('proposals', item)
