"""Remove a deleted work's conversation without touching other works or media."""
import json
from pathlib import Path


def purge(folder: Path, content_id: str):
    assistant = folder / 'assistant'
    if not assistant.exists():
        return
    for path in assistant.glob('*.json'):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except ValueError:
            continue
        context = data.get('context') if isinstance(data, dict) else None
        if isinstance(data, dict) and (data.get('content_id') == content_id or
                isinstance(context, dict) and context.get('content_id') == content_id):
            path.unlink()
    for path in (assistant / 'events').glob('*.jsonl'):
        lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
        kept = []
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                kept.append(line)
                continue
            if not isinstance(row, dict) or row.get('content_id') != content_id:
                kept.append(line)
        if len(kept) != len(lines):
            if kept:
                path.write_text(''.join(kept), encoding='utf-8')
            else:
                path.unlink()
