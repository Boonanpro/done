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
from follow_github import NO_WINDOW, _git, _out, line_endings_only, status  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
TRANSCRIPTS = [HOME / '.claude' / 'projects', HOME / '.codex' / 'sessions']
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

def _norm(path, cwd=None):
    s = str(path).strip()
    if not s:
        return None
    m = re.match(r'^/([a-zA-Z])(/.*)?$', s)
    if m and os.name == 'nt':
        s = f'{m.group(1).upper()}:{m.group(2) or "/"}'
    p = Path(s)
    if not p.is_absolute():
        if not cwd:
            return None
        p = Path(cwd) / p
    return os.path.normcase(os.path.normpath(str(p)))


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


def attribute(repo, paths, since):
    """rel path -> list of (time, session id, what was asked, transcript) of edit-tool writes to it, oldest first."""
    live = os.path.normcase(os.path.normpath(str(repo)))
    wanted = {os.path.normcase(p): p for p in paths}
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
                            hits.append(_norm(ti.get('file_path') or ti.get('notebook_path') or '', rec.get('cwd')))
                    session = rec.get('sessionId') or session
                elif rec.get('type') == 'response_item':
                    pl = rec.get('payload') or {}
                    if pl.get('type') in ('custom_tool_call', 'function_call'):
                        body = pl.get('input') or pl.get('arguments') or ''
                        body = body if isinstance(body, str) else json.dumps(body)
                        for raw in PATCH_HEAD.findall(body):
                            raw = ESCAPED_NEWLINE.split(raw, 1)[0].split('")', 1)[0].replace('\\\\', '\\')
                            hits.append(_norm(raw.strip(), cwd))
                for h in hits:
                    if h and h.startswith(live + os.sep):
                        rel = wanted.get(os.path.normcase(os.path.relpath(h, live).replace(os.sep, '/')))
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

def _hash(repo, rel):
    return _out(repo, 'hash-object', '--path', rel, '--', os.path.join(repo, rel)).decode().strip()


def move(repo, group):
    """Commit the group's files to a new branch, read the commit back, then put the folder's copies back.
    Returns (branch, commit, moved, left here because they changed meanwhile)."""
    repo = str(repo)
    branch = group['branch']
    if _git(repo, 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}').returncode == 0:
        n = 2
        while _git(repo, 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}-{n}').returncode == 0:
            n += 1
        branch = f'{branch}-{n}'
    head = _out(repo, 'rev-parse', 'HEAD').decode().strip()
    fd, index = tempfile.mkstemp(suffix='.index')
    os.close(fd)
    os.unlink(index)
    env = dict(os.environ, GIT_INDEX_FILE=index)     # a separate index: the folder's own is not touched
    hashed = {}
    try:
        def g(*args):
            p = _git(repo, *args, env=env)
            if p.returncode:
                raise RuntimeError(f"git {' '.join(args[:2])}: {p.stderr.decode('utf-8', 'replace').strip()[:300]}")
            return p.stdout
        g('read-tree', head)
        for f in group['files']:
            rel, full = f['path'], os.path.join(repo, f['path'])
            if os.path.isfile(full):
                blob = g('hash-object', '-w', '--path', rel, '--', full).decode().strip()
                old = _git(repo, 'ls-tree', head, '--', rel).stdout.split()
                g('update-index', '--add', '--cacheinfo', f"{old[0].decode() if old else '100644'},{blob},{rel}")
                hashed[rel] = (blob, f['mtime'])
            else:
                g('update-index', '--force-remove', '--', rel)
                hashed[rel] = (None, None)
        tree = g('write-tree').decode().strip()
        msg = (f"wip: rescued from the running folder ({len(hashed)} files)\n\n"
               f"Session: {group['session'] or 'none recorded'}\nAsked: {group['label'] or 'unknown'}\n\n"
               "Moved by scripts/rescue_wip.py on " + datetime.now().strftime('%Y-%m-%d %H:%M') + '.\n')
        commit = _out(repo, *IDENT, 'commit-tree', tree, '-p', head, '-m', msg).decode().strip()
        _out(repo, 'update-ref', f'refs/heads/{branch}', commit, '')         # create only, never move a branch
    finally:
        if os.path.exists(index):
            os.unlink(index)
    moved, kept = [], []
    for f in group['files']:
        rel, full = f['path'], os.path.join(repo, f['path'])
        blob, mt = hashed[rel]
        in_branch = _git(repo, 'rev-parse', '--verify', '--quiet', f'{commit}:{rel}').stdout.decode().strip() or None
        now_blob = _hash(repo, rel) if os.path.isfile(full) else None
        if in_branch != blob or now_blob != blob or (mt and _mtime(repo, rel) != mt):
            kept.append(rel)                                   # changed while we worked, or not read back: leave it
            continue
        if _git(repo, 'ls-files', '--error-unmatch', '--', rel).returncode == 0:
            if f['code'][:1] not in (' ', '?'):
                _out(repo, 'reset', '-q', head, '--', rel)     # staged here: unstage (the index only)
            _out(repo, 'checkout-index', '-f', '-u', '--', rel)
        elif blob is not None:
            os.unlink(full)
        moved.append(rel)
    return branch, commit, moved, kept


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
    if p['eol_only']:
        _out(repo, 'checkout-index', '-f', '-u', '--', *p['eol_only'])
    log = Path(repo) / '.data' / 'rescue_wip.jsonl'
    log.parent.mkdir(parents=True, exist_ok=True)
    for g in p['groups']:
        if g['busy']:
            print(f"\nskipped {g['branch']}: written within {quiet:.0f} minutes; run again later")
            continue
        branch, commit, moved, kept = move(repo, g)
        print(f"\n{branch} {commit[:8]}: moved {len(moved)}" + (f", left here (changed meanwhile) {kept}" if kept else ''))
        with log.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps({'at': datetime.now().isoformat(timespec='seconds'), 'branch': branch, 'commit': commit,
                                 'session': g['session'], 'label': g['label'], 'moved': moved, 'kept': kept},
                                ensure_ascii=False) + '\n')
    print('\nContinue a piece of work: python scripts/work.py new <name> --from <branch>')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
