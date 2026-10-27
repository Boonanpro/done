"""Gateway-owned durable dispatch, woken by file changes rather than AI turns."""
import asyncio
from pathlib import Path
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from app.services import command_job_state as state
from app.services.job_process import alive


def start():
    loop = asyncio.get_running_loop()
    tasks = {}
    async def consider(job_id):
        saved = state.read(job_id)
        if not saved or saved.get('queue_owner') != 'process' or alive(saved): return
        if not ((saved['state'] == 'queued' and not saved.get('runner_started')) or
                (saved['state'] == 'completed' and saved.get('delivery_pending'))): return
        from app.services.job_process import launch
        row = {'id': saved['id'], 'user_id': saved['user_id'], 'room_id': saved['room_id'],
               'spec': {k: saved[k] for k in ('origin_room_id', 'origin_project_id', 'task')}}
        await launch(row)
    def enqueue(job_id):
        if job_id not in tasks or tasks[job_id].done():
            task = tasks[job_id] = asyncio.create_task(consider(job_id))
            def finished(task):
                try: task.result()
                except asyncio.CancelledError: pass
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception('durable job dispatch failed')
            task.add_done_callback(finished)
    class Changed(FileSystemEventHandler):
        def on_any_event(self, event):
            if event.is_directory or event.event_type not in ('created', 'modified', 'moved'): return
            path = Path(getattr(event, 'dest_path', '') or event.src_path)
            if path.suffix == '.json': loop.call_soon_threadsafe(enqueue, path.stem)
    state.ROOT.mkdir(parents=True, exist_ok=True)
    observer = Observer(); observer.schedule(Changed(), str(state.ROOT), recursive=False); observer.start()
    for path in state.ROOT.glob('*.json'): enqueue(path.stem)
    def stop():
        observer.stop(); observer.join(timeout=3)
        # These monitors own no job process and cancellation never kills a job.
        for task in tasks.values(): task.cancel()
    return stop
