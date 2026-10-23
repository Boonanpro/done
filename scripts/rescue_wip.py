"""Move work left uncommitted in the running folder (D:\\done) onto branches, one branch per session that wrote it.

Since 2026-10-18 nobody writes the folder's tracked files (scripts/hook_live_tree_guard.py); this tool takes out what
was written before that, or slipped past it. Nothing is lost: each file goes into a commit on a branch
`wip/<date>-<session>` first, the commit is read back and compared with the file, and only then the folder's copy is put
back to the committed one (a new file is removed). Continue the work with
`python scripts/work.py new <name> --from wip/...`.

Who wrote a file is read from the sessions' own records: Claude Code transcripts (~/.claude/projects) and Codex
sessions (~/.codex/sessions), the latest write of each file by an edit tool, with what the person had asked just
before. Files written by a shell command or a program have no such record; they go to one branch per day, "unknown".

Left alone:
- a group with a file changed, or an edit recorded, within --quiet-minutes (default 30): it may still be being
  written. Run again later.
- files the target's .gitignore ignores (they stay as local files; follow_github keeps them).
- files that differ only by Windows line endings (nothing to keep; --apply puts back the committed text).

Usage: python scripts/rescue_wip.py [--repo D:/done] [--apply] [--quiet-minutes 30] [--target origin/main] [--json]
(--target: the commit whose .gitignore decides which files stay as local files)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from follow_github import NO_WINDOW, _git, _out, dan_dir, line_endings_only, live_root, status, tree_lock  # noqa: E402

ROOT = live_root()
HOME = Path.home()
TRANSCRIPTS = [HOME / '.claude' / 'projects', HOME / '.codex' / 'sessions',
               *(Path(x) for x in os.environ.get('DAN_TRANSCRIPTS', '').split(os.pathsep) if x)]
# Where the running folder was before (records written on the Windows PC say D:\\done)
ALIASES = [a for a in os.environ.get('DAN_LIVE_ALIASES', 'D:/done').split(os.pathsep) if a]
WRITE_TOOLS = {'Write', 'Edit', 'MultiEdit', 'NotebookEdit'}
PATCH_HEAD = re.compile(r'\*\*\* (?:Add File|Update File|Delete File|Move to): ([^\n]+)')
ESCAPED_NEWLINE = re.compile(r'\\n(?=[-+ @]|\*\*\* )')     # a patch written inside a script's string literal
WRAPPERS = ('runtime_system_context', 'conversation_so_far', 'room_state', 'system-reminder', 'recent_chat_full',
            'environment_context', 'user_instructions', 'INSTRUCTIONS')
USER_RECORD, USER_ROLE = re.compile(r'"type":\s*"user"'), re.compile(r'"role":\s*"user"')
IDENT = ['-c', 'user.name=Dan (rescue_wip)', '-c', 'user.email=dan-rescue@localhost']


# --- what is uncommitted -------------------------------------------------------------------------------------------------

def _ignored_on(repo, paths, target):
    if not paths:
        return set()
    ignore = _git(repo, 'show', f'{target}:.gitignore').stdout
    with tempfile.NamedTemporaryFile('wb', delete=False, suffix='.gitignore') as f:
        f.write(ignore)
    try:
        p = _git(repo, '-c', f'core.excludesFile={f.name}', 'check-ignore', '--no-index', '-z', '--stdin',
                 data=b'\0'.join(x.encode('utf-8', 'surrogateescape') for x in paths) + b'\0')
    finally:
        os.unlink(f.name)
    return {x.decode('utf-8', 'surrogateescape') for x in p.stdout.split(b'\0') if x}


def _mtime(repo, rel):
    try:
        return os.path.getmtime(os.path.join(repo, rel))
    except OSError:
        return None


# --- who wrote it --------------------------------------------------------------------------------------------------------

def _label(text):
    """What the person asked, from a user message as the session recorded it ('' for a message that is only context)."""
    text = text or ''
    if text.lstrip().startswith(('# AGENTS.md instructions', '<environment_context>', '<user_instructions>')):
        return ''
    found = re.findall(r'<latest_user_message>(.*?)</latest_user_message>', text, flags=re.S)
    if found:
        text = found[-1]
    elif '（ここから並行作業）' in text:
        text = text.split('（ここから並行作業）', 1)[1]
    else:
        for tag in WRAPPERS:
            text = re.sub(rf'<{tag}>.*?</{tag}>', ' ', text, flags=re.S)
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()[:90]


def _user_text(rec):
    """The text of a person's message in a Claude or Codex record, else None."""
    if rec.get('type') == 'user':
        content = (rec.get('message') or {}).get('content')
        if isinstance(content, str):
            return content
        if isinstance(content, list) and not any(isinstance(c, dict) and c.get('type') == 'tool_result' for c in content):
            return ' '.join(c.get('text', '') for c in content if isinstance(c, dict) and c.get('type') == 'text')
        return None
    pl = rec.get('payload') or {}
    if rec.get('type') == 'response_item' and pl.get('type') == 'message' and pl.get('role') == 'user':
        return ' '.join(c.get('text', '') for c in pl.get('content') or [] if isinstance(c, dict))
    return None


def _candidates(paths, since):
    """Transcript files written since `since` that mention one of the files' names."""
    names = sorted({os.path.basename(p) for p in paths if os.path.basename(p)})
    files = []
    for root in TRANSCRIPTS:
        for d, _, fs in os.walk(root):
            for f in fs:
                if f.endswith('.jsonl'):
                    full = os.path.join(d, f)
                    try:
                        if os.path.getmtime(full) >= since:
                            files.append(full)
                    except OSError:
                        pass
    if not names or not files:
        return []
    with tempfile.NamedTemporaryFile('w', delete=False, encoding='utf-8', suffix='.txt') as f:
        f.write('\n'.join(names))
    found = []
    try:
        for i in range(0, len(files), 150):
            try:
                p = subprocess.run(['rg', '-l', '-F', '-f', f.name, *files[i:i + 150]], capture_output=True,
                                   creationflags=NO_WINDOW)
                found += [x for x in p.stdout.decode('utf-8', 'replace').splitlines() if x.strip()]
            except FileNotFoundError:                    # no ripgrep: read them all
                found += files[i:i + 150]
    finally:
        os.unlink(f.name)
    return [Path(x) for x in found]


def _fold(s):
    return s.lower() if sys.platform in ('darwin', 'win32') else s


def _rel(raw, cwd, repo):
    """The path relative to the running folder (posix form) when raw points into it, under its current name or one
    it had before (ALIASES); else None."""
    s = str(raw or '').strip().replace('\\', '/')
    if not s:
        return None
    if not (s.startswith('/') or re.match(r'^[A-Za-z]:/', s)):
        if not cwd:
            return None
        s = str(cwd).replace('\\', '/').rstrip('/') + '/' + s
    s = re.sub(r'/+', '/', s)
    parts = []
    for part in s.split('/'):
        if part == '..' and parts:
            parts.pop()
        elif part not in ('.', ''):
            parts.append(part)
    s = ('/' if s.startswith('/') else '') + '/'.join(parts)
    roots = [str(repo), os.path.realpath(str(repo)), *ALIASES]
    for root in roots:
        root = root.replace('\\', '/').rstrip('/')
        if _fold(s).startswith(_fold(root) + '/'):
            return s[len(root) + 1:]
    return None


def attribute(repo, paths, since):
    """rel path -> list of (time, session id, what was asked, transcript) of edit-tool writes to it, oldest first."""
    wanted = {_fold(p): p for p in paths}
    names = {os.path.basename(p) for p in paths}
    edits = defaultdict(list)
    for tr in _candidates(paths, since):
        session, asked, cwd = tr.stem, '', None
        try:
            lines = tr.open(encoding='utf-8', errors='replace')
        except OSError:
            continue
        with lines:
            for line in lines:
                head = line[:160]
                if USER_RECORD.search(head) or ('"response_item"' in head and USER_ROLE.search(line[:600])):
                    if '"tool_result"' not in line[:3000]:
                        try:
                            asked = _label(_user_text(json.loads(line)) or '') or asked
                        except ValueError:
                            pass
                    continue
                if '"session_meta"' in head:
                    try:
                        meta = json.loads(line).get('payload') or {}
                        session, cwd = meta.get('id') or session, meta.get('cwd') or cwd
                    except ValueError:
                        pass
                    continue
                if not any(n in line for n in names):
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                hits = []
                if rec.get('type') == 'assistant':
                    for c in (rec.get('message') or {}).get('content') or []:
                        if isinstance(c, dict) and c.get('type') == 'tool_use' and c.get('name') in WRITE_TOOLS:
                            ti = c.get('input') or {}
                            hits.append(_rel(ti.get('file_path') or ti.get('notebook_path') or '', rec.get('cwd'), repo))
                    session = rec.get('sessionId') or session
                elif rec.get('type') == 'response_item':
                    pl = rec.get('payload') or {}
                    if pl.get('type') in ('custom_tool_call', 'function_call'):
                        body = pl.get('input') or pl.get('arguments') or ''
                        body = body if isinstance(body, str) else json.dumps(body)
                        for raw in PATCH_HEAD.findall(body):
                            raw = ESCAPED_NEWLINE.split(raw, 1)[0].split('")', 1)[0].replace('\\\\', '\\')
                            hits.append(_rel(raw.strip(), cwd, repo))
                for h in hits:
                    if h:
                        rel = wanted.get(_fold(h))
                        if rel:
                            edits[rel].append((rec.get('timestamp') or '', session, asked, str(tr)))
    for v in edits.values():
        v.sort()
    return edits


def _utc_seconds(stamp):
    try:
        return datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()
    except (ValueError, AttributeError):
        return 0


# --- the plan ------------------------------------------------------------------------------------------------------------

def plan(repo=ROOT, quiet_minutes=30.0, target='origin/main'):
    repo = str(repo)
    items = status(repo)
    codes = {p: c for c, p in items}
    eol = line_endings_only(repo, [p for c, p in items if c == ' M'])
    rest = [p for p in codes if p not in eol]
    local = _ignored_on(repo, rest, target)
    work = [p for p in rest if p not in local]
    times = [t for t in (_mtime(repo, p) for p in work) if t]
    since = (min(times) if times else time.time()) - 86400
    edits = attribute(repo, work, since)
    now, quiet = time.time(), quiet_minutes * 60
    groups = {}
    for p in work:
        mt = _mtime(repo, p)
        mine = edits.get(p) or []
        if mine:
            when, session, asked, _ = mine[-1]
            g = groups.setdefault(f'session:{session}', {'session': session, 'label': '', 'files': [], 'last': ''})
            if when >= g['last']:
                g['last'], g['label'] = when, asked or g['label']
        else:                    # one branch a day; a file still being written waits alone, not with the day's others
            day = datetime.fromtimestamp(mt or now).strftime('%Y%m%d')
            fresh = '-now' if mt and now - mt < quiet else ''
            g = groups.setdefault(f'unknown:{day}{fresh}', {'session': None, 'files': [], 'last': '',
                                                    'label': '編集の記録が無い変更（シェルや別の仕組みが書いた）'})
        g['files'].append({'path': p, 'code': codes[p], 'mtime': mt,
                           'others': sorted({e[1] for e in mine[:-1]} - {g['session']})})
    for key, g in groups.items():
        stamps = [f['mtime'] for f in g['files'] if f['mtime']]
        g['busy'] = (now - max(stamps + [_utc_seconds(g['last'])] or [0])) < quiet
        day = datetime.fromtimestamp(max(stamps) if stamps else now).strftime('%Y%m%d')
        g['branch'] = f"wip/{day}-{g['session'][:8]}" if g['session'] else f"wip/{key.split(':', 1)[1]}-unknown"
    return {'eol_only': sorted(eol), 'local': sorted(local), 'groups': sorted(groups.values(), key=lambda g: g['branch'])}


# --- moving ---------------------------------------------------------------------------------------------------------------
# Two steps, never mixed: first every file is saved in a commit on a branch and read back (save), then the folder's copies
# are put back to the committed ones (restore). The folder's copy is never deleted: it is moved into
# .git/dan/rescued/<time>/ (never a change in git's eyes), so even a write that lands in the instant between the two steps survives.

def _hash(repo, rel):
    full = os.path.join(repo, rel)
    if os.path.islink(full):
        return _out(repo, 'hash-object', '--stdin', data=os.readlink(full).encode('utf-8', 'surrogateescape')).decode().strip()
    return _out(repo, 'hash-object', '--path', rel, '--', full).decode().strip()


def _entry(repo, ref, rel):
    """(mode, blob) of rel in a commit, or None."""
    out = _git(repo, 'ls-tree', '-z', ref, '--', rel).stdout.split(b'\0')[0].decode('utf-8', 'surrogateescape')
    if not out:
        return None
    mode, _, blob = out.split('\t', 1)[0].split()
    return mode, blob


def _index_entry(repo, rel):
    out = _git(repo, 'ls-files', '-s', '-z', '--', rel).stdout.split(b'\0')[0].decode('utf-8', 'surrogateescape')
    if not out:
        return None
    mode, blob, _stage = out.split('\t', 1)[0].split()
    return mode, blob


def _worktree_entry(repo, rel, env=None):
    """(mode, blob) of the file as it is in the folder (written into git's object store), or None when it is gone."""
    full = os.path.join(repo, rel)
    if os.path.islink(full):
        blob = _out(repo, 'hash-object', '-w', '--stdin', data=os.readlink(full).encode('utf-8', 'surrogateescape'))
        return '120000', blob.decode().strip()
    if not os.path.isfile(full):
        return None
    blob = _out(repo, 'hash-object', '-w', '--path', rel, '--', full).decode().strip()
    return ('100755' if os.access(full, os.X_OK) else '100644'), blob


def _commit(repo, parent, entries, msg):
    """A commit on top of parent with entries {rel: (mode, blob) or None (removed)}; built in a separate index."""
    fd, index = tempfile.mkstemp(suffix='.index')
    os.close(fd)
    os.unlink(index)
    env = dict(os.environ, GIT_INDEX_FILE=index)       # the folder's own index is not touched
    try:
        def g(*args, data=None):
            p = _git(repo, *args, data=data, env=env)
            if p.returncode:
                raise RuntimeError(f"git {' '.join(args[:2])}: {p.stderr.decode('utf-8', 'replace').strip()[:300]}")
            return p.stdout
        g('read-tree', parent)
        for rel, e in entries.items():
            if e is None:
                g('update-index', '--force-remove', '--', rel)
            else:
                g('update-index', '--add', '--cacheinfo', f'{e[0]},{e[1]},{rel}')
        tree = g('write-tree').decode().strip()
    finally:
        if os.path.exists(index):
            os.unlink(index)
    if tree == _out(repo, 'rev-parse', f'{parent}^{{tree}}').decode().strip():
        return parent
    return _out(repo, *IDENT, 'commit-tree', tree, '-p', parent, '-m', msg).decode().strip()


def _free_branch(repo, branch):
    if _git(repo, 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}').returncode:
        return branch
    n = 2
    while _git(repo, 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}-{n}').returncode == 0:
        n += 1
    return f'{branch}-{n}'


def save(repo, group, append=False):
    """Commit the group's files to a branch and read the commit back. Changes nothing in the folder.
    A file staged with `git add` and changed again afterwards keeps both versions: the staged one in a first commit,
    the folder's one in the next. append=True adds to the branch when it exists (the guard's sweep of one session).
    Returns (branch, commit, saved) with saved = {rel: blob in the folder, or None for a file deleted here}."""
    repo = str(repo)
    head = _out(repo, 'rev-parse', 'HEAD').decode().strip()
    branch = group['branch']
    old = None
    if append and _git(repo, 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}').returncode == 0:
        old = _out(repo, 'rev-parse', f'refs/heads/{branch}').decode().strip()
    elif not append:
        branch = _free_branch(repo, branch)
    files = [f['path'] for f in group['files']]
    staged, here = {}, {}
    for f in group['files']:
        rel = f['path']
        if f['code'][:1] not in (' ', '?'):
            staged[rel] = _index_entry(repo, rel)
        here[rel] = _worktree_entry(repo, rel)
    about = (f"Session: {group.get('session') or 'none recorded'}\nAsked: {group.get('label') or 'unknown'}\n\n"
             f"Moved by scripts/rescue_wip.py on {datetime.now().strftime('%Y-%m-%d %H:%M')}.\n")
    parent = old or head
    if staged and any(staged[r] != here[r] for r in staged):
        parent = _commit(repo, parent, staged, f'wip: staged with git add in the running folder ({len(staged)} files)\n\n{about}')
    commit = _commit(repo, parent, here, f'wip: rescued from the running folder ({len(files)} files)\n\n{about}')
    if commit == (old or head):
        return branch, commit, {}                                 # nothing that differs: nothing to save
    _out(repo, 'update-ref', f'refs/heads/{branch}', commit, old or '')   # create (or move only from what we read)
    saved = {}
    for rel in files:
        want = here[rel]
        got = _entry(repo, commit, rel)
        if got != want and not (want is None and got is None):
            raise RuntimeError(f'{rel}: the branch {branch} does not hold what the folder has; nothing was put back')
        saved[rel] = want[1] if want else None
    return branch, commit, saved


def restore(repo, rel, expected, keep_dir, same=None):
    """Put the folder's rel back to the commit HEAD, if it still is what was saved (blob `expected`, None = deleted;
    or, given `same`, when same(path of the moved copy) says so). The folder's copy is moved (not deleted) into
    keep_dir first. Returns 'restored' or 'changed' (left as it is)."""
    repo = str(repo)
    full = os.path.join(repo, rel)
    aside = Path(keep_dir) / rel
    if expected is None and same is None:
        if os.path.lexists(full):
            return 'changed'                                       # recreated since it was saved
    else:
        if not os.path.lexists(full):
            return 'changed'
        aside.parent.mkdir(parents=True, exist_ok=True)
        os.replace(full, aside)                                    # atomic: a writer from now on writes to its own new file
        if not (same(aside) if same else _hash_path(repo, rel, aside) == expected):                                      # written after it was saved: give it back untouched
            if not os.path.lexists(full):
                os.replace(aside, full)
            return 'changed'
    head = _entry(repo, 'HEAD', rel)
    if head:
        _out(repo, 'update-index', '--add', '--cacheinfo', f'{head[0]},{head[1]},{rel}')
        if not os.path.lexists(full):
            _git(repo, 'checkout-index', '-u', '--', rel)          # no -f: never over a file written meanwhile
    else:
        _git(repo, 'update-index', '--force-remove', '--', rel)
    return 'restored'


def _hash_path(repo, rel, path):
    path = str(path)
    if os.path.islink(path):
        return _out(repo, 'hash-object', '--stdin', data=os.readlink(path).encode('utf-8', 'surrogateescape')).decode().strip()
    return _out(repo, 'hash-object', '--path', rel, '--', path).decode().strip()


def _eol_only(repo, rel, path):
    head = _git(repo, 'cat-file', 'blob', f'HEAD:{rel}')
    try:
        here = Path(path).read_bytes()
    except OSError:
        return False
    return head.returncode == 0 and b'\0' not in here and here.replace(b'\r\n', b'\n') == head.stdout.replace(b'\r\n', b'\n')


def keep_dir(repo):
    return dan_dir(repo) / 'rescued' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')


def _journal_file(repo):
    return dan_dir(repo) / 'rescue_journal.jsonl'


def _journal(repo):
    """{(rel, blob): branch} of everything rescue_wip has saved before, so a run cut short is finished without a
    second copy: a file whose content is already on a branch is only put back."""
    out = {}
    try:
        for line in _journal_file(repo).read_text(encoding='utf-8').splitlines():
            rec = json.loads(line)
            if _git(repo, 'cat-file', '-e', f"{rec['commit']}^{{commit}}").returncode == 0:
                for rel, blob in (rec.get('saved') or {}).items():
                    out[(rel, blob)] = rec['branch']
    except (OSError, ValueError, KeyError):
        pass
    return out


def _write_journal(repo, rec):
    with _journal_file(repo).open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
        fh.flush()
        os.fsync(fh.fileno())


def apply(repo, p, quiet):
    """Save every group first; only when all are saved, put the folder back. Safe to run again after a stop."""
    repo = str(repo)
    done = _journal(repo)
    where = keep_dir(repo)
    lines, saved_all = [], []
    for g in p['groups']:
        if g['busy']:
            lines.append(f"skipped {g['branch']}: written within {quiet:.0f} minutes; run again later")
            continue
        current = {f['path']: (_hash(repo, f['path']) if os.path.lexists(os.path.join(repo, f['path'])) else None)
                   for f in g['files']}
        todo = dict(g, files=[f for f in g['files'] if (f['path'], current[f['path']]) not in done])
        saved = {f['path']: current[f['path']] for f in g['files'] if (f['path'], current[f['path']]) in done}
        branch = commit = None
        if todo['files']:
            branch, commit, more = save(repo, todo)
            saved.update(more)
            _write_journal(repo, {'at': datetime.now().isoformat(timespec='seconds'), 'branch': branch, 'commit': commit,
                                  'session': g['session'], 'label': g['label'], 'saved': more})
        saved_all.append((g, branch, commit, saved))
    for g, branch, commit, saved in saved_all:                     # everything is on branches now
        kept = [rel for rel, blob in saved.items() if restore(repo, rel, blob, where) != 'restored']
        name = branch or next((done[k] for k in saved.items() if k in done), '(saved before)')
        lines.append(f"{name} {(commit or '')[:8]}: moved {len(saved) - len(kept)}"
                     + (f", left here (changed meanwhile) {kept}" if kept else ''))
    for rel in p['eol_only']:                  # nothing to keep in them: put back only if that is still true
        if os.path.lexists(os.path.join(repo, rel)):
            restore(repo, rel, None, where, same=lambda path, rel=rel: _eol_only(repo, rel, path))
    return lines


# --- the command ---------------------------------------------------------------------------------------------------------

def _show(p):
    out = []
    if p['groups']:
        out.append(f"{len(p['groups'])} branches to make ({sum(len(g['files']) for g in p['groups'])} files):")
    for g in p['groups']:
        flag = '  [待つ: 書かれたばかり]' if g['busy'] else ''
        out.append(f"\n{g['branch']}{flag}\n  {g['label'] or '(依頼の文が記録に無い)'}")
        if g['session']:
            out.append(f"  session {g['session']}  last edit {g['last'][:16].replace('T', ' ')} UTC")
        for f in g['files']:
            when = datetime.fromtimestamp(f['mtime']).strftime('%m-%d %H:%M') if f['mtime'] else 'deleted'
            also = f"  (also edited by {', '.join(o[:8] for o in f['others'])})" if f['others'] else ''
            out.append(f"    {f['code'].strip() or '?':>2} {f['path']}  {when}{also}")
    if p['eol_only']:
        out.append(f"\nWindows line endings only, nothing to keep ({len(p['eol_only'])}): " + ', '.join(p['eol_only']))
    if p['local']:
        out.append(f"\nStay as local files (the .gitignore ignores them) ({len(p['local'])}): "
                   + ', '.join(p['local'][:12]) + (' ...' if len(p['local']) > 12 else ''))
    if not (p['groups'] or p['eol_only']):
        out.append('Nothing uncommitted here that holds work.')
    return '\n'.join(out)


def main(argv):
    sys.stdout.reconfigure(encoding='utf-8')
    repo = argv[argv.index('--repo') + 1] if '--repo' in argv else str(ROOT)
    quiet = float(argv[argv.index('--quiet-minutes') + 1]) if '--quiet-minutes' in argv else 30.0
    target = argv[argv.index('--target') + 1] if '--target' in argv else 'origin/main'
    p = plan(repo, quiet, target)
    print(json.dumps(p, ensure_ascii=False, indent=1) if '--json' in argv else _show(p))
    if '--apply' not in argv:
        if p['groups']:
            print('\n(dry run: nothing moved. --apply moves the groups not marked 待つ)')
        return 0
    with tree_lock(repo) as held:
        if not held:
            print('another tool is changing the folder right now; nothing moved. Run again.')
            return 1
        for line in apply(repo, p, quiet):
            print('\n' + line)
    print('\nContinue a piece of work: python scripts/work.py new <name> --from <branch>')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
