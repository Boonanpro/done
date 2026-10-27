"""Restore the active release after a host/process restart, without replaying work."""
import asyncio
import os
from pathlib import Path
import select
import sys

from app.core import generations as G


async def exited(owner):
    if not G.living(owner): return
    if not hasattr(select, 'kqueue'):
        while G.living(owner): await asyncio.sleep(2)
        return
    queue = select.kqueue()
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    try:
        try:
            queue.control([select.kevent(owner['pid'], filter=select.KQ_FILTER_PROC,
                           flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT, fflags=select.KQ_NOTE_EXIT)], 0, 0)
        except ProcessLookupError: return
        def ready():
            if not future.done(): future.set_result(None)
        loop.add_reader(queue.fileno(), ready)
        if not G.living(owner): return
        await future
    finally:
        loop.remove_reader(queue.fileno()); queue.close()


async def restore(release):
    import psutil
    # Ports may still be held by a live Sandbox with calls. Core may attach to
    # that existing port; it must never kill a listener in order to restart.
    root = Path(release['root'])
    env = G.core_env(DAN_GENERATION=release['id'], DAN_CORE_PORT='9000',
                     DAN_SANDBOX_PORT=str(release['sandbox']), PYTHONUNBUFFERED='1')
    with (G.ROOT / (release['id'] + '.log')).open('ab') as log:
        process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'uvicorn', 'app.core.main:app',
            '--host', '127.0.0.1', '--port', str(release['core']), '--loop', 'app.core.event_loop:new_loop',
            cwd=root, env=env, stdin=asyncio.subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    release = {**release, 'owner': {'pid': process.pid, 'created': psutil.Process(process.pid).create_time()}}
    G.write('release-' + release['id'], release)
    # Do not overwrite a concurrent activation of another release.
    if (G.read('active') or {}).get('id') == release['id']: G.write('active', release)
    return release


def start():
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
    loop = asyncio.get_running_loop()
    tasks = {}
    async def watch(release):
        failures = 0
        while (G.read('active') or {}).get('id') == release['id']:
            if not G.living(release.get('owner')):
                if failures >= 3:
                    import logging
                    logging.getLogger(__name__).error('Active release could not stay up; automatic restarts stopped')
                    return
                release = await restore(release)
                failures += 1
            await exited(release['owner'])
            # A normal switch drains and retires the old process. Never restart it.
            if (G.read('active') or {}).get('id') != release['id']: return
            await asyncio.sleep(1)
    def changed():
        release = G.read('active')
        if release and release['id'] not in tasks:
            tasks[release['id']] = asyncio.create_task(watch(release))
    class Changed(FileSystemEventHandler):
        def on_any_event(self, event):
            path = Path(getattr(event, 'dest_path', '') or event.src_path)
            if path.name == 'active.json' and event.event_type in ('created', 'modified', 'moved'):
                loop.call_soon_threadsafe(changed)
    G.ROOT.mkdir(parents=True, exist_ok=True)
    observer = Observer(); observer.schedule(Changed(), str(G.ROOT), recursive=False); observer.start()
    changed()
    def stop():
        observer.stop(); observer.join(timeout=3)
        for task in tasks.values(): task.cancel()
    return stop
