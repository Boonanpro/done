"""One journal for screen edits and versions of the editing skill shipped from its learning worktree."""
import fcntl
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from app.paths import DAN_WORKSPACE, LIVE_ROOT
from app.services import prompt_store


def _merge(base, edited, learned):
    if edited == base or edited == learned:
        return learned
    with TemporaryDirectory() as folder:
        paths = []
        for name, value in [('edited', edited), ('base', base), ('learned', learned)]:
            path = Path(folder) / name
            path.write_text(value + '\n', encoding='utf-8')
            paths.append(str(path))
        # A later lesson wins on the same passage. Earlier versions stay restorable.
        out = subprocess.run(['git', 'merge-file', '-p', '--theirs', *paths],
                             capture_output=True, text=True, check=True)
        return out.stdout.rstrip('\n')


def version(item, value=None, by='dan', note='', base_sha=None):
    """Read or save while locked across workers. A revision records its exact repository base."""
    journal = prompt_store._history_path(item['id'])
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open('a+', encoding='utf-8') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        # Running releases overlap. All of them use the skill in the followed checkout.
        repo = prompt_store.REPO
        if repo.parent == DAN_WORKSPACE / 'releases' and not os.environ.get('DAN_PROMPTS_DIR'):
            repo = LIVE_ROOT
        source = (repo / item['source_file']).read_text(encoding='utf-8').strip('\n')
        stream.seek(0)
        rows = []
        while True:
            offset = stream.tell()
            line = stream.readline()
            if not line:
                break
            if not line.endswith('\n'):
                stream.seek(offset)
                stream.truncate()
                break
            rows.append(json.loads(line))
        previous = rows[-1] if rows else {}

        def record(content, author, reason):
            row = dict(text=content, sha=prompt_store.sha(content), at=prompt_store._now(),
                       by=author, note=reason, source_text=source)
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
            return row

        if not previous:
            previous = record(source, 'seed', '編集の手順書から読み込み')
        elif previous.get('source_text') != source:
            base = previous.get('source_text', rows[0]['text'])
            merged = _merge(base, previous['text'], source)
            previous = record(merged, 'dan', '手順書の更新を反映。同じ箇所は新しい決定を採用')
        if value is None:
            return previous['text']
        if base_sha and base_sha != previous['sha']:
            raise RuntimeError('開いている間に内容が変わりました。開き直してください。')
        if value == previous['text']:
            return {'saved': False, 'sha': previous['sha']}
        row = record(value, by, note[:500])
        return {'saved': True, 'sha': row['sha'], 'at': row['at']}
