"""Work state pushed to the owner's screens the moment it changes (no polling).

A job's state lives in a file under command_job_state.ROOT, written by the core and by the separate worker processes.
The OS tells this watcher when a file changes; the core then publishes one event on the owner's room feed (the same
live connection the chat already uses): the room, the job, its newest event, and the call screen's one line.
The phone's call screen had asked every 3 seconds (on Android not at all until 2026-09-30); the owner wanted it live
(2026-10-01).
"""
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DEBOUNCE_S = 0.15   # a job writes several changes in a burst; send the settled one
_started = False


def _event_for(job_id):
    from app.services import command_job_state as state
    from app.services.voice_parts import status_line
    s = state.read(job_id)
    if not s:
        return None, None
    room = s.get('origin_room_id') or s.get('room_id')
    line = status_line(state.list_owned(s['user_id'], room)) if room else None
    newest = (s.get('events') or [{}])[-1]
    return s['user_id'], {'type': 'job', 'room_id': room, 'job_id': job_id, 'state': s.get('state'), 'seq': s.get('seq', 0),
                          'kind': newest.get('kind'), 'text': str(newest.get('text') or '')[:300], 'line': line, 'at': time.time()}


def start():
    """Start watching the job files (core only, once)."""
    global _started
    if _started:
        return
    _started = True
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
    from app.services import command_job_state as state
    from app.services.room_feed import publish
    state.ROOT.mkdir(parents=True, exist_ok=True)
    pending, lock = {}, threading.Lock()

    def flush(job_id):
        with lock:
            pending.pop(job_id, None)
        try:
            user_id, event = _event_for(job_id)
            if user_id and event:
                publish([user_id], event)
        except Exception:
            logger.exception('job feed publish failed for %s', job_id)

    class Changed(FileSystemEventHandler):
        def on_any_event(self, event):
            if event.is_directory: return
            name = Path(getattr(event, 'dest_path', '') or event.src_path).name
            if not name.endswith('.json'): return
            job_id = name[:-5]
            with lock:
                if job_id in pending: return
                timer = threading.Timer(DEBOUNCE_S, flush, (job_id,))
                pending[job_id] = timer
            timer.start()

    observer = Observer()
    observer.daemon = True
    observer.schedule(Changed(), str(state.ROOT), recursive=False)
    observer.start()
    logger.info('job feed watching %s', state.ROOT)
