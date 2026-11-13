"""Fonts the editable scenes (and their export) can use.

Two places: the free fonts bundled with the editor (frontend/public/fonts) and the owner's own
fonts (~/.dan/fonts, not in git: commercial or client fonts such as a client's Mincho or an
Envato font). ~/.dan/fonts/fonts.json lists the owner's fonts as
[{"family": "SoukouMincho", "file": "SoukouMincho.ttf", "label": "装甲明朝"}].
Scenes name the family in CSS; the frame declares every registered family and the browser
only downloads the ones a scene actually uses.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUNDLED = PROJECT_ROOT / 'frontend' / 'public' / 'fonts'
# same families as caption-design.ts CAPTION_FONT_FILES
_BUNDLED = [
    ('NotoSansJP', 'NotoSansJP.ttf', '100 900', 'Noto Sans JP'),
    ('DelaGothicOne', 'DelaGothicOne-Regular.ttf', '400', 'Dela Gothic One'),
    ('ZenMaruGothic', 'ZenMaruGothic-Black.ttf', '900', 'Zen丸ゴシック'),
    ('ReggaeOne', 'ReggaeOne-Regular.ttf', '400', 'Reggae One'),
    ('MPLUSRounded', 'MPLUSRounded1c-ExtraBold.ttf', '800', 'M PLUS Rounded'),
    ('RocknRollOne', 'RocknRollOne-Regular.ttf', '400', 'RocknRoll One'),
    ('ShipporiMincho', 'ShipporiMincho-ExtraBold.ttf', '800', 'しっぽり明朝'),
]


def owner_dir() -> Path:
    return Path(os.environ.get('DAN_FONTS_DIR') or Path.home() / '.dan' / 'fonts')


def registry() -> list[dict]:
    out = [{'family': f, 'file': file, 'weight': w, 'label': label, 'source': 'bundled'}
           for f, file, w, label in _BUNDLED if (BUNDLED / file).exists()]
    listing = owner_dir() / 'fonts.json'
    try:
        own = json.loads(listing.read_text(encoding='utf-8')) if listing.exists() else []
    except (OSError, ValueError):
        own = []
    for item in own if isinstance(own, list) else []:
        if not isinstance(item, dict) or not item.get('family') or not item.get('file'):
            continue
        if (owner_dir() / Path(str(item['file'])).name).exists():
            out.append({'family': str(item['family']), 'file': Path(str(item['file'])).name,
                        'weight': str(item.get('weight') or ''), 'label': str(item.get('label') or item['family']),
                        'source': 'owner'})
    return out


def registry_json() -> str:
    safe = [{k: v for k, v in f.items() if k in ('family', 'file', 'weight', 'label')} for f in registry()]
    return json.dumps(safe, ensure_ascii=False).replace('<', '\\u003c')


def font_path(name: str) -> Path | None:
    name = Path(name).name
    for f in registry():
        if f['file'] == name:
            base = BUNDLED if f['source'] == 'bundled' else owner_dir()
            p = base / name
            return p if p.exists() else None
    return None
