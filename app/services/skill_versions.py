"""One journal for screen edits and versions of the editing skill shipped from its learning worktree."""
import fcntl
import json
import os
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from app.paths import DAN_WORKSPACE, LIVE_ROOT
from app.services import prompt_store


def skill_root():
    # All running releases see the same repository lessons and untracked case pages.
    repo = prompt_store.REPO
    if repo.parent == DAN_WORKSPACE / 'releases' and not os.environ.get('DAN_PROMPTS_DIR'):
        repo = LIVE_ROOT
    return repo / '.claude' / 'skills'


def _page(root, path):
    # Only Markdown belonging to an installed skill. Never follow links out of the collection.
    relative = path.relative_to(root)
    if (path.resolve() != root.resolve() / relative or path.suffix != '.md'
            or any(part.startswith('.') for part in relative.parts)
            or not path.is_file()):
        raise KeyError(str(relative))
    return relative


def _entry(root, path):
    relative = _page(root, path)
    if not (root / relative.parts[0] / 'SKILL.md').is_file():
        raise KeyError(str(relative))
    key = relative.parent if relative.name == 'SKILL.md' and len(relative.parts) == 2 else relative.with_suffix('')
    with path.open(encoding='utf-8') as stream:
        head = stream.read(8192)
    heading = re.search(r'^# (.+)$', head, re.M)
    display = re.search(r'^display_name:\s*(.+)$', head, re.M)
    label = display if relative.name == 'SKILL.md' and display else heading
    title = label[1].strip().strip('"') if label else key.name
    source = f'.claude/skills/{relative.as_posix()}'
    return dict(id=f'skill/{key.as_posix()}', title=title, place='chat', kind='skill',
                reader='このスキルを使うダン', when='この作業に取りかかる時', source=source, source_file=source)


def skill_entry(prompt_id):
    parts = prompt_id.split('/')[1:]
    if not parts or any(not part or part.startswith('.') or '\\' in part or '\x00' in part for part in parts):
        raise KeyError(prompt_id)
    relative = Path(*parts)
    path = relative / 'SKILL.md' if len(parts) == 1 else Path(str(relative) + '.md')
    root = skill_root()
    item = _entry(root, root / path)
    if item['id'] != prompt_id:
        raise KeyError(prompt_id)
    return item


def skill_pages():
    root = skill_root()
    for manual in sorted(root.glob('*/SKILL.md')):
        for path in sorted(manual.parent.rglob('*.md')):
            try:
                yield _entry(root, path)
            except (KeyError, FileNotFoundError):
                continue


def page_text(path):
    """Read the same revision as the screen for Dan's normal skill-file reads."""
    if path.suffix != '.md' or '.claude' not in path.parts:
        return None
    path = path.absolute()
    for root in (prompt_store.REPO / '.claude/skills', skill_root()):
        if not path.is_relative_to(root):
            continue
        relative = path.relative_to(root)
        try:
            item = _entry(skill_root(), skill_root() / relative)
            return prompt_store.text(item['id'])
        except KeyError:
            return None
    return None


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
        root = skill_root()
        path = root.parent.parent / item['source_file']
        _page(root, path)
        source = path.read_text(encoding='utf-8').strip('\n')
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
            previous = record(source, 'seed', 'スキルの元の文')
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
