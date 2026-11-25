"""Reports from work in another room, kept for this room's Dan instead of written into its chat.

The finished work of a delegated room used to be posted into the asking room as「【<部屋>からの報告】…」. A job's own
report and the automatic one on completion both landed, often saying nothing the owner had to do, and the owner found
the chat drowned in them (2026-11-25「うるさすぎる。意味無いチャット汚れる」). Now the report is kept here; the asking
room's Dan reads it with the next turn (chat_routes._fetch_unseen_voice_digest) and tells the owner in its own words
only what matters. The full result stays in the work room itself.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get('DAN_ROOM_REPORTS_ROOT') or Path.home() / '.dan' / 'room-reports')
KEEP_SECONDS = 14 * 86400


def _path(room_id: str) -> Path:
    if not room_id or '/' in room_id or room_id.startswith('.'):
        raise ValueError('invalid room')
    return ROOT / f'{room_id}.jsonl'


def add(room_id: str, *, source_title: str, source_room_id: str, text: str) -> dict:
    ROOT.mkdir(parents=True, exist_ok=True)
    row = {'at': datetime.now(timezone.utc).isoformat(), 'source_title': source_title or '',
           'source_room_id': source_room_id or '', 'text': text}
    with _path(room_id).open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    return row


def since(room_id: str, floor: float) -> list[dict]:
    """Reports that arrived after the unix time `floor`, oldest first. Old lines are dropped on the way."""
    path = _path(room_id)
    if not path.exists():
        return []
    rows, kept = [], []
    cutoff = time.time() - KEEP_SECONDS
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            row = json.loads(line)
            at = datetime.fromisoformat(row['at']).timestamp()
        except (ValueError, KeyError, TypeError):
            continue
        if at >= cutoff:
            kept.append(line)
        if at >= floor:
            rows.append(row)
    if len(kept) < len(path.read_text(encoding='utf-8').splitlines()):
        path.write_text(''.join(k + '\n' for k in kept), encoding='utf-8')
    return rows
