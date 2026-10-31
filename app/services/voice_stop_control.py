"""Conservative stop fallback for a single job started in this call.

Native Live delegation may acknowledge a stop without invoking any tool. Only
an entire, explicit stop utterance is eligible; ambiguous targets stay with the
normal conversational path. Never match a substring or stop another room.
"""
import asyncio
from datetime import datetime
import re


def explicit_stop(text):
    text = re.sub(r'[\s、。！？!?]', '', text)
    return bool(re.fullmatch(r'(?:一旦|いったん)?(?:その|今の|この)?作業(?:を)?(?:止めて|とめて|中止して)(?:ください|下さい|ね)?', text))


class StopControl:
    def __init__(self, user, room, started_at, send, record):
        self.user, self.room, self.started_at = user, room, started_at
        self.send, self.record = send, record
        self.text, self.end_ms = '', None
        self.timer = None
        self.closed = False
        self.handled = set()

    def heard(self, delta, start_ms=None, end_ms=None):
        if self.closed or not delta:
            return
        # Transcript timing, not assistant interjections, separates utterances.
        if (self.end_ms is not None and isinstance(start_ms, (int, float))
                and start_ms - self.end_ms > 1200):
            self.text = ''
        self.text = (self.text + delta)[-300:]
        if isinstance(end_ms, (int, float)):
            self.end_ms = end_ms
        if self.timer:
            self.timer.cancel()
        self.timer = asyncio.create_task(self._settle(self.text))

    async def _settle(self, text):
        await asyncio.sleep(1.2)
        self.timer = None
        if not self.closed and explicit_stop(text):
            await self.stop_one()

    async def stop_one(self):
        from app.services import command_job_state as state
        try:
            jobs = await asyncio.to_thread(state.list_owned, self.user, self.room)
            # Any second active job makes "that task" ambiguous, even if older.
            active = [j for j in jobs if j['state'] not in state.TERMINAL]
            if len(jobs) >= 20 or len(active) != 1:
                self.record('stop_fallback_skipped', reason='ambiguous_or_no_active_job')
                return
            job = active[0]
            if (job['id'] in self.handled or job.get('room_id') != self.room
                    or datetime.fromisoformat(job['created_at']) < datetime.fromisoformat(self.started_at)):
                return
            self.handled.add(job['id'])  # no retry after an uncertain mutation
            await asyncio.to_thread(state.control, job['id'], self.user, self.room, 'cancel')
            self.record('stop_fallback_accepted', job_id=job['id'][:8])
            await self.send({'type': 'session.commentary.append', 'delegation_id': None,
                'content': '今この通話で始めた作業への停止指示を受け付けました。実行終了の確認前に「停止済み」とは言わないでください。'})
        except Exception as exc:
            self.record('stop_fallback_failed', error_type=type(exc).__name__)

    def close(self):
        self.closed = True
        if self.timer:
            self.timer.cancel()
