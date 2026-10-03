"""Every published site's source is also kept in Git (owner, 2026-10-03).

Sites are written under D:/done/frontend/src/app/artifacts/<slug> (not tracked by D:/done) and deployed straight to their
own Vercel projects. The commit to done-artifacts that used to come with a publish stopped when GitHub was suspended
(2026-07-28) and was never brought back: from 2026-08-18 on the sources lived only on this disk. Now each successful
publish mirrors its slug into the done-artifacts working tree and commits it there.

GitHub at a human pace (the suspension was caused by a retry loop): commits are local and immediate; a push happens at
most once per PUSH_HOURS, one attempt, never retried. An authentication or permission failure stops all pushing until
the stop file is removed by hand, and the owner is told once."""
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)
SOURCE = Path(__file__).resolve().parents[2]/'frontend'/'src'/'app'/'artifacts'
REPO = Path(os.environ.get('DAN_ARTIFACTS_REPO', 'D:/done-artifacts'))
TARGET = REPO/'src'/'app'/'artifacts'
STATE = Path.home()/'.dan'/'artifact-archive'
STOP = STATE/'push-stopped'
PUSH_HOURS = 3
# shared infrastructure, tracked by D:/done itself (and kept separately in done-artifacts): never mirrored per site
SKIP = {'[slug]', '_seo', 'publish', 'editable-lp-lab', 'floor-lp-compare', 'floor-lp-native'}
_lock = threading.Lock()
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def _git(*args, timeout=60):
    return subprocess.run(['git', *args], cwd=REPO, capture_output=True, text=True, encoding='utf-8', errors='replace',
                          timeout=timeout, creationflags=_NO_WINDOW)


def _mirror(slug):
    src, dst = SOURCE/slug, TARGET/slug
    if not src.is_dir():
        return False
    if dst.exists():
        for path in sorted(dst.rglob('*'), reverse=True):   # files removed at the source are removed here too
            rel = path.relative_to(dst)
            if not (src/rel).exists():
                path.unlink() if path.is_file() else shutil.rmtree(path, ignore_errors=True)
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns('node_modules', '.next', '*.bak', 'bak_*'))
    return True


def slugs():
    return sorted(p.name for p in SOURCE.iterdir() if p.is_dir() and p.name not in SKIP) if SOURCE.is_dir() else []


def record(slug_list, message=''):
    """Mirror these slugs into done-artifacts and commit what changed. Returns the commit hash or ''."""
    if not REPO.is_dir():
        return ''
    with _lock:
        mirrored = [s for s in slug_list if s not in SKIP and _mirror(s)]
        if not mirrored:
            return ''
        _git('add', '--', *[f'src/app/artifacts/{s}' for s in mirrored])
        if not _git('diff', '--cached', '--quiet').returncode:
            return ''
        msg = message or ('publish: ' + ', '.join(mirrored))
        done = _git('commit', '-q', '-m', msg, '-m', 'Recorded by Dan at publish (app/services/artifact_archive.py).')
        if done.returncode:
            logger.warning('artifact archive: commit failed: %s', (done.stderr or done.stdout)[-300:])
            return ''
        head = _git('rev-parse', '--short', 'HEAD').stdout.strip()
        logger.info('artifact archive: %s committed %s', ', '.join(mirrored), head)
    push_if_due()
    return head


def push_if_due(force=False):
    """One push at a human pace. Never retried; an auth failure stops pushing until STOP is removed by hand."""
    if STOP.exists():
        return 'stopped'
    STATE.mkdir(parents=True, exist_ok=True)
    stamp = STATE/'last-push'
    try:
        last = float(stamp.read_text())
    except (OSError, ValueError):
        last = 0
    if not force and time.time() - last < PUSH_HOURS*3600:
        return 'later'
    ahead = _git('rev-list', '--count', '@{u}..HEAD')
    if ahead.returncode == 0 and ahead.stdout.strip() == '0':
        return 'nothing'
    stamp.write_text(str(time.time()))
    result = _git('push', '-q', 'origin', 'HEAD', timeout=120)
    if result.returncode == 0:
        logger.info('artifact archive: pushed')
        return 'pushed'
    text = (result.stderr or result.stdout or '')[-400:]
    if any(w in text.lower() for w in ('403', '401', 'suspended', 'denied', 'authentication', 'permission')):
        STOP.write_text(text, encoding='utf-8')
        logger.warning('artifact archive: push refused, pushing stopped until %s is removed: %s', STOP, text)
        try:
            from app.services import inbox
            from app.services.owner import resolve_owner_user_id
            inbox.say_soon(resolve_owner_user_id(), None, '成果物の記録（done-artifacts）を GitHub へ送ろうとして、認証・権限で断られました。'
                           '再試行はしていません（止めてあります）。原因を確かめてから再開します。')
        except Exception:
            pass
        return 'refused'
    logger.warning('artifact archive: push failed (will try at the next due time): %s', text)
    return 'failed'


def record_soon(slug):
    """From the publish job: in its own thread (git must never hold up a deploy)."""
    threading.Thread(target=lambda: _safe(record, [slug]), name=f'artifact-archive-{slug}', daemon=True).start()


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception:
        logger.exception('artifact archive failed')
