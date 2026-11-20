"""Reference scripts shown beside a talk script on the /script-listen screen (2026-11-20).

The owner works on scripts on the listen screen and compares them with the scripts of the videos they
were modelled on. Each script (Google Doc) has its own file ~/.dan/script-listen/references/<doc_id>.json:

    {"refs": [{"id": "itsuki-arigatou", "who": "イツキ", "title": "今までありがとう。",
               "url": "https://www.youtube.com/watch?v=…", "length": "9:41", "note": "どう書き起こしたか",
               "sections": [{"match": "11万人の皆さんへ、今までありがとう", "start": 0, "text": "…"}, …]}]}

A section's ``match`` is the heading of the script it lines up with (▼/◎/【】 and spaces are ignored when
matching); a section with no ``match`` found lines up by its order among the read headings. ``start`` is
the second in the video (null when that part is not in the video), ``text`` the spoken words.
The files hold other people's scripts (the owner's, clients', creators'), so they stay on this Mac.

Write one from Dan:  python -m app.services.script_listen_refs <doc id or url> <file.json>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DIR = Path.home() / '.dan' / 'script-listen' / 'references'


def _doc_id(value: str) -> str:
    m = re.search(r'/document/d/([A-Za-z0-9_-]+)', value)
    return (m.group(1) if m else value).strip()


def _path(doc_id: str) -> Path:
    if not re.fullmatch(r'[A-Za-z0-9_-]{10,}', doc_id):
        raise ValueError('ドキュメントのIDが正しくありません。')
    return DIR / f'{doc_id}.json'


def _clean(data: dict) -> dict:
    refs = []
    for r in data.get('refs') or []:
        sections = []
        for s in r.get('sections') or []:
            start = s.get('start')
            sections.append({
                'match': str(s.get('match') or ''),
                'start': int(start) if isinstance(start, (int, float)) else None,
                'text': str(s.get('text') or '').strip(),
            })
        if not sections:
            continue
        refs.append({
            'id': str(r.get('id') or f'ref{len(refs) + 1}'),
            'who': str(r.get('who') or ''),
            'title': str(r.get('title') or ''),
            'url': str(r.get('url') or ''),
            'length': str(r.get('length') or ''),
            'note': str(r.get('note') or ''),
            'sections': sections,
        })
    return {'refs': refs}


def read(doc_id: str) -> dict:
    p = _path(doc_id)
    if not p.exists():
        return {'refs': []}
    return _clean(json.loads(p.read_text(encoding='utf-8')))


def save(doc_id: str, data: dict) -> dict:
    clean = _clean(data)
    p = _path(doc_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(p)
    return clean


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    data = save(_doc_id(argv[0]), json.loads(Path(argv[1]).read_text(encoding='utf-8')))
    for r in data['refs']:
        filled = sum(1 for s in r['sections'] if s['text'])
        print(f"{r['who']}「{r['title']}」 段 {filled}/{len(r['sections'])}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
