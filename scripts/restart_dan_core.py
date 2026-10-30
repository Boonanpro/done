"""Stop dan core + sandbox (listeners on 9000/8000 and their start_dan_core/uvicorn
process tree), wait for the ports to free. Launching a fresh core is done
separately so it can run in the background. After it starts, scripts/verify_dan.py checks that real work goes through.

Before stopping, the folder is brought up to GitHub main (scripts/follow_github.py), so a restart loads what was
pushed and not only what happens to be in the folder. A folder that cannot follow is left as it is and said so.

  (no option)    stop now; refuses while a call, a turn or parallel work is running, or when the code does not load
  --force        stop even then (only when the owner agreed)
  --when-idle --then "<what to check afterwards>"    for Dan itself (2026-10-13). Dan's turn runs inside the core, so
      stopping the core ends the turn that asked. This hands the whole restart to a process outside the core: it waits
      until nothing is running (the asking turn included; up to a day, new automatic work held for the first 5 min), brings the folder up to GitHub main, checks that the code on
      disk loads, stops, has the watchdog start the core, runs verify_dan.py, and wakes Dan in the asking room with the
      outcome.

On the Mac (2026-10-24) launchd's com.dan.core starts the core again by itself (KeepAlive) and the core starts the
sandbox; on Windows the DanStackWatchdog task does.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

PORTS = {8000, 9000}
ROOT = Path(__file__).resolve().parents[1]
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def listeners():
    found = {}
    for c in connections():
        if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port in PORTS and c.pid:
            found.setdefault(c.pid, set()).add(c.laddr.port)
    return found


def connections():
    """Every listening socket this user can see. On macOS the system-wide psutil.net_connections() raises AccessDenied
    as soon as it meets another user's process (2026-10-24: a restart handed over at 01:32 died there silently), so
    there each process is asked on its own and the ones that refuse are skipped; the core and sandbox are ours."""
    if sys.platform != 'darwin':
        return psutil.net_connections(kind="inet")
    out = []
    for p in psutil.process_iter():
        try:
            out.extend(Conn(p.pid, c) for c in p.net_connections(kind="inet"))
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    return out


class Conn:
    """A per-process connection (which carries no pid) shaped like psutil.net_connections()'s rows."""
    __slots__ = ('pid', 'status', 'laddr')

    def __init__(self, pid, c):
        self.pid, self.status, self.laddr = pid, c.status, c.laddr


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


WAIT = 24 * 60 * 60  # a restart Dan asked for waits up to this long for everyone to finish (2026-10-30 本人「空いてるのに
                     # それに気づかず機を逃すということが無いように」: it used to give up after 5 min and the core stayed old)
DRAIN = 5 * 60       # for this long new automatic work (followups, core jobs) is held so the running work can drain;
                     # after that it runs again and the wait only listens for the first moment nothing runs
POLL = 5             # rechecked this often besides the change notices (a call's quiet time ends without one)
BACK_UP = 5 * 60      # and this long for the core and sandbox to answer again
WATCHDOG = r'\DanStackWatchdog'
LAUNCHD_JOB = 'com.dan.core'
GENERATIONS = Path.home() / '.dan' / 'generations' / 'enabled'   # release switching is on (2026-10-27)


def loads():
    """Why the code on disk would not start, or None. Asked before stopping: a core that cannot start cannot wake Dan
    to say what went wrong."""
    p = subprocess.run([sys.executable, '-c', 'import app.core.main, app.sandbox.main'], cwd=str(ROOT),
                       capture_output=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
    return None if p.returncode == 0 else (p.stderr or '').strip()[-1500:]


def follow_github():
    """(True, what happened) once the folder is on GitHub main; (False, why) when it was left as it is."""
    p = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'follow_github.py')], cwd=str(ROOT), capture_output=True,
                       encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
    return p.returncode == 0, (p.stdout or p.stderr or 'follow_github.py printed nothing').strip()[:1200]


def core_started_at():
    return max((psutil.Process(pid).create_time() for pid, ports in listeners().items() if 9000 in ports), default=0)


def healthy():
    import urllib.request
    try:
        return all(urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=5).status == 200 for port in sorted(PORTS))
    except Exception:
        return False


def start():
    """True once the core and sandbox answer. The watchdog task starts them, as it does after a crash: started from
    here they would inherit the environment of the Dan turn that asked (its room, its locks)."""
    deadline = time.time() + BACK_UP
    if sys.platform == 'darwin':
        # KeepAlive starts the core again within ThrottleInterval (20 s); kickstart without -k only starts a job that
        # is not running, so it never kills the one launchd may already have started.
        subprocess.run(['launchctl', 'kickstart', f'gui/{os.getuid()}/{LAUNCHD_JOB}'], capture_output=True)
    else:
        subprocess.run(['schtasks', '/Run', '/TN', WATCHDOG], capture_output=True, creationflags=NO_WINDOW)
    while time.time() < deadline:
        if healthy():
            return True
        time.sleep(3)
    return False


def verify():
    p = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'verify_dan.py')], cwd=str(ROOT), capture_output=True,
                       encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
    return ((p.stdout or '').strip().splitlines() or ['verify_dan.py printed nothing'])[-1][:500]


def wake(room, note):
    """Have Dan start a turn in the room with the note. The row is in the database, so it waits for a core that is
    still coming up."""
    from app.services.followups import schedule_followup
    from app.services.supabase_client import get_supabase_client
    with open(ROOT / 'logs' / 'restart_dan_core.log', 'a', encoding='utf-8') as f:
        f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + room[:8] + ' ' + note + chr(10))
    owner = (get_supabase_client().client.table('chat_room_members').select('user_id')
             .eq('room_id', room).eq('role', 'owner').limit(1).execute().data or [{}])[0].get('user_id')
    schedule_followup(room, note, 15, owner)


def earlier_restart():
    """Another restart that was handed over before this one and has not finished, or None. Two that both saw "nothing
    is running" would have the second stop the core the first had just started; the later one waits and then finds the
    core already new."""
    me = psutil.Process()
    for p in psutil.process_iter(['cmdline', 'create_time']):
        cl = p.info.get('cmdline') or []
        if '--outside' in cl and any(a.endswith('restart_dan_core.py') for a in cl) and (p.info['create_time'], p.pid) < (me.create_time(), me.pid):
            return f'an earlier restart is under way (pid {p.pid})'
    return None


def asking_room():
    """The room of the Dan turn running this. A Codex turn has DAN_ROOM_ID; a Claude room's long-lived session has only
    its lock owner, "room:<id>" (seen 2026-10-13: Dan had to pass --room by hand)."""
    owner = os.environ.get('DAN_LOCK_OWNER', '')
    return os.environ.get('DAN_ROOM_ID') or (owner[5:] if owner.startswith('room:') else '')


def restart_when_idle(room, then, asked):
    """The part that runs outside the core. Nobody reads its output, so a failure is told to the room, never dropped."""
    try:
        return _restart_when_idle(room, then, asked)
    except Exception as exc:
        import traceback
        where = traceback.extract_tb(exc.__traceback__)[-1]
        note = (f'本体の再起動の途中で失敗した（{type(exc).__name__}: {str(exc)[:300]}、'
                f'{Path(where.filename).name}:{where.lineno}）。本体が動いているか、9000 / 8000 番の /health を確かめる。')
        try:
            with open(ROOT / 'logs' / 'restart_dan_core.log', 'a', encoding='utf-8') as f:
                f.write(traceback.format_exc())
        except OSError:
            pass
        wake(room, note)


def _restart_when_idle(room, then, asked):
    after = '続けて確かめること: ' + then if then else ''
    from app.services.restart_signal import waiting, wait, hold
    # Keep the hold through preflight and the actual switch; release before the
    # verification job, which needs the normal dispatch path.
    deadline = time.monotonic() + WAIT
    drained = time.monotonic() + DRAIN
    # A later helper must not hold the earlier helper's verification job.
    while earlier_restart():
        if time.monotonic() >= deadline:
            return wake(room, '先に頼まれた再起動が続いているため、この重複した待機を終了した。自動再予約はしない。')
        time.sleep(1)
    with waiting(WAIT + BACK_UP + 120) as signal:
        folder = ''
        prepared = False
        held = True
        while True:
            reason = busy() or earlier_restart()
            if not reason and not held:
                # Hold new automatic work again for the switch, then make sure nothing slipped in meanwhile.
                hold(signal, True)
                held = True
                continue
            if not reason:
                if core_started_at() > asked:
                    note = '本体は頼んだ後に別の再起動で新しくなっていたので、もう一度は止めていない。'
                    break
                if not prepared:
                    followed, github = follow_github()
                    folder = chr(10) + ('フォルダと GitHub: ' if followed else 'フォルダを GitHub に追いつかせられなかった: ') + github
                    problem = loads()
                    if problem:
                        return wake(room, '本体を再起動していない。コードが読み込めない:' + chr(10) + problem + folder)
                    prepared = True
                    # Work may have started during preflight. Recheck before stop.
                    continue
                if not stop():
                    return wake(room, '本体を止めきれなかった（9000 / 8000 番が空かない）。再起動は終わっていない。')
                at = time.strftime('%H:%M')
                if not start():
                    return wake(room, f'本体を {at} に止めたが、{BACK_UP // 60}分たっても起き上がらなかった。dan_core.log の末尾を見る。')
                note = f'本体を {at} に再起動した。'
                break
            prepared = False   # the folder is brought up to GitHub again for the moment that is idle
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return wake(room, f'本体の再起動は{WAIT // 3600}時間待ったが空かなかったので終了した。作業は止めていない（{reason}）。'
                            '同じ待機や確認の自動再予約はしない。阻害している作業を調べ、安全な対応を判断する。')
            if held and time.monotonic() >= drained:
                hold(signal, False)
                held = False
            wait(signal, min(POLL, remaining))
    wake(room, note + '動作確認: ' + verify() + '。' + after + folder)


def hand_over(room, then):
    """The part Dan runs: start the outside process and return."""
    problem = loads()
    if problem:
        print('NOT restarting: the code on disk does not load' + chr(10) + problem)
        sys.exit(2)
    cmd = [sys.executable, str(Path(__file__).resolve()), '--when-idle', '--outside', '--room', room, '--then', then,
           '--asked', str(time.time())]
    mine = ('DAN_SESSION_ID', 'DAN_ROOM_ID', 'DAN_LOCK_OWNER', 'DAN_PROJECT_ID', 'CLAUDECODE')   # the asking turn's, not the check's
    quiet = dict(cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                 env={k: v for k, v in os.environ.items() if k not in mine})
    if os.name != 'nt':
        # Its own session: launchd ends the rest of com.dan.core's process group when the core exits, and the asking
        # CLI's group is ended with the turn.
        p = subprocess.Popen(cmd, start_new_session=True, **quiet)
    else:
        apart = NO_WINDOW | getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        try:   # out of any job the asking CLI holds its children in, when the job allows leaving
            p = subprocess.Popen(cmd, creationflags=apart | getattr(subprocess, 'CREATE_BREAKAWAY_FROM_JOB', 0), **quiet)
        except OSError:
            p = subprocess.Popen(cmd, creationflags=apart, **quiet)
    print(f'handed over (pid {p.pid}). The core restarts the moment no call, turn or parallel work is running; your own '
          f'turn counts, so finish it. You are woken in this room with the outcome (it waits up to {WAIT // 3600} h).')


def option(name, default=''):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv[:-1] else default


def main():
    valued = ('--room', '--then', '--asked')
    unknown = [a for i, a in enumerate(sys.argv) if i and a.startswith('-') and sys.argv[i - 1] not in valued
               and a not in ('--force', '--when-idle', '--outside') + valued]
    if unknown:   # `--help` used to fall through to a restart (Dan tried it first, 2026-10-13)
        print(__doc__)
        sys.exit(2)
    if GENERATIONS.exists():
        # No idle wait: new work moves to a verified release while existing
        # turns/calls remain on their original processes.
        sys.path.insert(0, str(ROOT))
        from core_release import prepare, activate
        release = prepare(ROOT)
        activate(release['id'])
        print('New requests use the new release. Existing work continues.')
        if '--when-idle' not in sys.argv:
            return
        # Chat turns still run on the shared core (9000), which a release switch leaves as it is (2026-10-30: fixes to
        # chat waited there for days), so it is restarted too, the moment nothing runs.
    if '--when-idle' in sys.argv:
        room = option('--room', asking_room())
        if not room:
            print('NOT restarting: no room to report back to (pass --room <room id>)')
            sys.exit(2)
        if '--outside' in sys.argv:
            sys.path.insert(0, str(ROOT))
            return restart_when_idle(room, option('--then'), float(option('--asked', '0')))
        return hand_over(room, option('--then'))
    reason = None if '--force' in sys.argv else busy()
    if reason:
        print('NOT restarting:', reason, '(pass --force only when the owner agreed)')
        sys.exit(3)
    followed, github = follow_github()
    print('folder and GitHub:' if followed else 'WARNING, the folder was NOT brought up to GitHub (left as it is):', github)
    problem = loads()
    if problem:
        print('NOT restarting: the code on disk does not load' + chr(10) + problem)
        sys.exit(2)
    if not stop():
        print("WARNING: ports still occupied")
        sys.exit(1)
    print("OK: 9000 and 8000 are free")
    print("next: start the core, then run  python scripts/verify_dan.py  (a real job through the call entry; health 200 is not enough)")


def announce():
    """Tell every open screen that the core is about to stop: they show "restarting" until it answers again."""
    import urllib.request
    try:
        urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:9000/api/v1/chat/internal/restarting', data=b'{}', method='POST'), timeout=3)
        time.sleep(0.5)   # the event leaves the core before the core is killed
    except Exception:
        pass   # an older core, or one that no longer answers: the screens notice when their line drops


def stop():
    """End the core and sandbox with their process trees. True when both ports are free."""
    announce()
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
    if '--force' not in sys.argv:
        reason = busy()
        if reason:
            raise RuntimeError('再起動直前に作業が始まったため、中止した: ' + reason)
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
    return not after


if __name__ == "__main__":
    main()
