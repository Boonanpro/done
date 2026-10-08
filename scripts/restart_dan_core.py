"""Stop dan core + sandbox (listeners on 9000/8000 and their start_dan_core/uvicorn
process tree), wait for the ports to free. Launching a fresh core is done
separately so it can run in the background. After it starts, scripts/verify_dan.py checks that real work goes through.
"""
import sys
import time
import psutil

PORTS = {8000, 9000}


def listeners():
    found = {}
    for c in psutil.net_connections(kind="inet"):
        if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port in PORTS and c.pid:
            found.setdefault(c.pid, set()).add(c.laddr.port)
    return found


def busy():
    """Why a restart now would break something the owner is using, or None. A restart kills the call's server side and
    running API jobs. Checked here, right before killing, and a call that ended less than QUIET seconds ago counts too:
    on 2026-09-24 the owner called back 19 s after hanging up and a restart made after a clean check broke that call."""
    import json
    from datetime import datetime, timezone
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    reasons = []
    try:
        from app.core.api.sandbox_routes import _live_phone_calls
        if _live_phone_calls():
            reasons.append('a phone call is open')
    except Exception as exc:
        reasons.append(f'cannot check calls ({type(exc).__name__})')
    log = root / '.tmp' / 'voice-sideband.jsonl'
    if log.exists():
        with log.open('rb') as f:
            f.seek(max(0, log.stat().st_size - 200_000))
            tail = f.read().decode('utf-8', 'replace').splitlines()
        for line in reversed(tail):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get('phase') in ('sideband_closed', 'sideband_attached', 'sideband_event'):
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(row['at'])).total_seconds()
                if age < QUIET:
                    reasons.append(f'the last call activity was {age:.0f}s ago (wait {QUIET}s)')
                break
    jobs = [p.pid for p in psutil.process_iter(['cmdline']) if 'api_job_worker' in ' '.join(p.info.get('cmdline') or [])]
    if jobs:
        reasons.append(f'API jobs are running (pids {jobs})')
    reasons.extend(work_in_progress())
    return '; '.join(reasons) or None


WAITING_FOR_OWNER = {'paused', 'awaiting_confirmation', 'awaiting_approval'}


def work_in_progress():
    """Chat turns and parallel work that a restart would cut off. On 2026-10-08 11:50 a restart made after this check
    passed (it looked only at calls and API jobs) ended two turns in the middle; one was moving the owner's camera files.
    Read from the records every backend writes the same way (agent_runs, the job state files), so a Codex turn counts
    like a Claude turn. Work waiting for the owner's answer is not running: it is printed and does not stop the restart
    (the owner's decision, 2026-10-08; one such run had been waiting since the night before)."""
    reasons = []
    try:
        from app.services.run_service import ACTIVE_RUN_STATES
        from app.services.supabase_client import get_supabase_client
        sb = get_supabase_client().client
        runs = sb.table('agent_runs').select('room_id,state').in_('state', list(ACTIVE_RUN_STATES)).execute().data or []
        ids = list({r['room_id'] for r in runs if r.get('room_id')})
        names = {r['id']: r.get('name') for r in (sb.table('chat_rooms').select('id,name').in_('id', ids).execute().data or [])} if ids else {}
        label = lambda r: names.get(r.get('room_id')) or str(r.get('room_id'))[:8]
        waiting = sorted({label(r) for r in runs if r['state'] in WAITING_FOR_OWNER})
        running = sorted({label(r) for r in runs if r['state'] not in WAITING_FOR_OWNER})
        if waiting:
            print('note: waiting for the owner (not stopping the restart):', ', '.join(waiting))
        if running:
            reasons.append('Dan is working in: ' + ', '.join(running))
    except Exception as exc:
        reasons.append(f'cannot check chat turns ({type(exc).__name__})')
    try:
        from app.services import command_job_state as state
        active = []
        for p in state.ROOT.glob('*.json'):
            s = state.read(p.stem)
            if s and s.get('state') == 'running':
                active.append(str(s.get('task') or s['id'])[:30])
        if active:
            reasons.append('parallel work is running: ' + ' / '.join(active))
    except Exception as exc:
        reasons.append(f'cannot check parallel work ({type(exc).__name__})')
    return reasons


QUIET = 120


def main():
    reason = None if '--force' in sys.argv else busy()
    if reason:
        print('NOT restarting:', reason, '(pass --force only when the owner agreed)')
        sys.exit(3)
    me = psutil.Process().pid
    l = listeners()
    print("listeners before:", {pid: sorted(ports) for pid, ports in l.items()})

    targets = set()
    for pid in l:
        try:
            p = psutil.Process(pid)
            targets.add(pid)
            for par in p.parents():
                try:
                    cl = " ".join(par.cmdline())
                except Exception:
                    cl = ""
                if "start_dan_core" in cl or "uvicorn" in cl:
                    targets.add(par.pid)
        except Exception as e:
            print("inspect err", pid, e)

    procs = []
    for pid in targets:
        if pid == me:
            continue
        try:
            pr = psutil.Process(pid)
            for ch in pr.children(recursive=True):
                if ch.pid != me:
                    procs.append(ch)
            procs.append(pr)
        except Exception:
            pass
    # dedup
    seen, uniq = set(), []
    for pr in procs:
        if pr.pid not in seen:
            seen.add(pr.pid)
            uniq.append(pr)
    print("terminating PIDs:", sorted(p.pid for p in uniq))
    for pr in uniq:
        try:
            pr.terminate()
        except Exception:
            pass
    gone, alive = psutil.wait_procs(uniq, timeout=8)
    for pr in alive:
        try:
            pr.kill()
        except Exception:
            pass
    time.sleep(2)
    after = listeners()
    print("listeners after:", {pid: sorted(ports) for pid, ports in after.items()})
    if after:
        print("WARNING: ports still occupied")
        sys.exit(1)
    print("OK: 9000 and 8000 are free")
    print("next: start the core, then run  python scripts/verify_dan.py  (a real job through the call entry; health 200 is not enough)")


if __name__ == "__main__":
    main()
