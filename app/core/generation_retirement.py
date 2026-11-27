"""Retire only drained workers. Nothing has a deadline that kills live work."""
import asyncio
from pathlib import Path
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from app.core import generations as G
from app.services.job_process import lease

# Per target port, counts all gateway streams, including WebSockets and requests
# that have not created a run yet. The stable gateway is the sole public entrance.
connections = {}

# What an older release reports as busy although it is only its upkeep (named upkeep: from 2026-11-28).
UPKEEP_LOOPS = {'app.services.run_reconciler.loop', 'app.services.voice_tools.Host._read'}


def enter(port): connections[port] = connections.get(port, 0) + 1

def leave(port): connections[port] = max(0, connections.get(port, 0) - 1)


def quiescent(release):
    import json
    import urllib.request
    from app.services.browser_lifecycle import _token_path
    try:
        token = _token_path().read_text().strip()
        for kind in ('core', 'sandbox'):
            request = urllib.request.Request(f"http://127.0.0.1:{release[kind]}/internal/generation/activity",
                                             headers={'x-dan-browser-token': token})
            with urllib.request.urlopen(request, timeout=2) as response:
                activity = json.load(response)
            # Releases from 2026-11-27 name what they run but count their upkeep loops as work.
            if not activity.get('idle') and not (activity.get('busy') and set(activity['busy']) <= UPKEEP_LOOPS): return False
        return True
    except Exception:
        return False


def superseded(release, active_release):
    created = (release.get('owner') or {}).get('created')
    active_created = (active_release.get('owner') or {}).get('created')
    return bool(created and active_created and created < active_created)


def retire_once():
    import psutil
    with lease(G.ROOT / 'activation.lock') as locked:
        if not locked: return
        active_release = G.read('active') or {}
        active = active_release.get('id')
        for path in G.ROOT.glob('release-*.json'):
            release = G.read(path.stem)
            if not release or release['id'] == active or release.get('retired'): continue
            # A release prepared before the active one and never activated is a superseded candidate (a restart
            # that prepared again). Nothing routes to it; it held a Core, a Sandbox and ports for good (2026-11-28).
            if not release.get('draining') and not superseded(release, active_release): continue
            if any(connections.get(release[k], 0) for k in ('core', 'sandbox')) or any(G.refs(release['id'])): continue
            if G.living(release.get('owner')) and not quiescent(release): continue
            if G.living(release.get('owner')):
                # Core gracefully stops only its own Sandbox. Jobs are detached
                # and browsers belong to the stable services, not this process.
                psutil.Process(release['owner']['pid']).terminate()
            release['retired'] = True
            G.write(path.stem, release)


def start():
    loop = asyncio.get_running_loop()
    queued = False
    def changed():
        nonlocal queued
        if queued: return
        queued = True
        async def finish():
            nonlocal queued
            # Let the run's final response drain before considering retirement.
            await asyncio.sleep(.2)
            try: retire_once()
            finally: queued = False
        asyncio.create_task(finish())
    class Changed(FileSystemEventHandler):
        def on_any_event(self, event):
            if event.event_type in ('created', 'modified', 'moved', 'deleted') and not event.is_directory:
                name = Path(getattr(event, 'dest_path', '') or event.src_path).name
                if name.endswith('.json'): loop.call_soon_threadsafe(changed)
    G.ROOT.mkdir(parents=True, exist_ok=True)
    observer = Observer(); observer.schedule(Changed(), str(G.ROOT), recursive=False); observer.start()
    changed()
    def stop(): observer.stop(); observer.join(timeout=3)
    return stop, changed
