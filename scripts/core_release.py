"""Prepare a verified pair of worker processes, then atomically switch new work.

Usage: core_release.py prepare [--root PATH]; core_release.py activate ID;
       core_release.py status
Preparation starts no shared pollers, calls or test accounts. Activation changes
only routing; no running process is terminated. Releases live in immutable git
worktrees so old processes never import files from a newer release mid-turn.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core import generations as G


def healthy(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=3) as response:
            body = json.load(response)
            return response.status == 200 and body.get('status') == 'healthy' and not body.get('broken_modules')
    except Exception:
        return False


def port_free(port):
    with socket.socket() as sock:
        try: sock.bind(('127.0.0.1', port)); return True
        except OSError: return False


def link_shared(destination, live):
    """Runtime data/artifacts are shared, tracked Python code is immutable."""
    for relative in ('.env', '.data', '.tmp', 'uploads', 'frontend/src/app/artifacts', 'frontend/public/artifacts'):
        target, source = destination / relative, live / relative
        if source.exists() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(source, target_is_directory=source.is_dir())
        elif source.is_dir() and target.is_dir() and not target.is_symlink():
            # The artifacts folders hold a few tracked files (layout.tsx, [slug]) next to the sites, which git does not
            # track: link each site the release lacks, or its _server routes and files are missing from the release
            # (2026-10-27: the call's stage found no X room).
            for child in source.iterdir():
                if not (target / child.name).exists():
                    (target / child.name).symlink_to(child, target_is_directory=child.is_dir())


def prepare(root):
    root = Path(root).resolve()
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    # The release is built exclusively from the committed tree. Unrelated
    # local notes or runtime files in the live folder cannot affect it and
    # must not become another global barrier to updating Dan.
    release_id = commit[:12] + '-' + uuid.uuid4().hex[:6]
    destination = Path.home() / 'dan-workspace' / 'releases' / release_id
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'worktree', 'add', '--detach', str(destination), commit], cwd=root, check=True)
    link_shared(destination, Path.home() / 'done')
    pair = next(((p, p - 1000) for p in range(9201, 9299) if port_free(p) and port_free(p - 1000)), None)
    if pair is None: raise RuntimeError('No free release ports')
    core, sandbox = pair
    env = {**os.environ, 'DAN_GENERATION': release_id, 'DAN_SANDBOX_PORT': str(sandbox),
           'DAN_CORE_PORT': '9000', 'PYTHONUNBUFFERED': '1'}
    G.ROOT.mkdir(parents=True, exist_ok=True)
    with (G.ROOT / (release_id + '.log')).open('ab') as log:
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.core.main:app',
                                    '--host', '127.0.0.1', '--port', str(core),
                                    '--loop', 'app.core.event_loop:new_loop'],
                                   cwd=destination, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=log, start_new_session=True)
    import psutil
    release = {'id': release_id, 'commit': commit, 'root': str(destination), 'core': core, 'sandbox': sandbox,
               'owner': {'pid': process.pid, 'created': psutil.Process(process.pid).create_time()}}
    G.write('release-' + release_id, release)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None: raise RuntimeError('New release exited before readiness: ' + release_id)
        if healthy(core) and healthy(sandbox):
            with urllib.request.urlopen(f'http://127.0.0.1:{sandbox}/openapi.json', timeout=10) as response:
                release['sandbox_routes'] = list(json.load(response).get('paths', {}))
            G.write('release-' + release_id, release)
            print(json.dumps({k: v for k, v in release.items() if k != 'sandbox_routes'})); return release
        time.sleep(.5)
    # Leave active untouched. Keep the failed candidate for diagnosis; never
    # terminate a process by a port or accidentally touch the running release.
    raise RuntimeError('New release did not become ready: ' + release_id)


def activate(release_id):
    from app.services.job_process import lease
    with lease(G.ROOT / 'activation.lock') as locked:
        if not locked: raise RuntimeError('Another activation is in progress')
        return _activate(release_id)


def _activate(release_id):
    release = G.read('release-' + release_id)
    if not release or release.get('retired') or not G.living(release.get('owner')) or not all(healthy(release[k]) for k in ('core', 'sandbox')):
        raise RuntimeError('Release not ready; routing was not changed')
    previous = G.read('active')
    if previous is None:
        from app.services.supabase_client import get_supabase_client
        from app.services.run_service import ACTIVE_RUN_STATES
        rows = get_supabase_client().client.table('agent_runs').select('id,room_id,metadata').in_('state', list(ACTIVE_RUN_STATES)).execute().data or []
        rooms = {}
        for row in rows:
            if (row.get('metadata') or {}).get('started_by') == 'command_center': continue
            rooms.setdefault(row['room_id'], []).append(row['id'])
        for room, runs in rooms.items(): G.write(G.key('legacy', room), {'runs': runs})
    if previous: G.write('previous', previous)
    G.write('active', release)
    if previous and previous['id'] != release_id:
        previous['draining'] = True
        G.write('release-' + previous['id'], previous)
    print(json.dumps({'active': release_id, 'previous': (previous or {}).get('id')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'activate', 'status'])
    parser.add_argument('release', nargs='?')
    parser.add_argument('--root', default=str(ROOT))
    args = parser.parse_args()
    if args.action == 'prepare': prepare(args.root)
    elif args.action == 'activate': activate(args.release)
    else: print(json.dumps({'active': G.read('active'), 'previous': G.read('previous')}, indent=2))
