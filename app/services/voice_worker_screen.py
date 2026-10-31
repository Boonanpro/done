"""Carry a worker's actual browser view into its owner's active call."""
import asyncio
import os


async def observe(job_id, tool, arguments):
    from app.services import command_job_state as state
    from app.services.voice_external_screen import NO_SCREEN
    if tool not in {'browser', 'browser_plan', 'browser_flow'} or arguments.get('action') in NO_SCREEN:
        return
    # Ask the executor used by this very operation, never a second browser.
    from app.tools.browser import _send_executor_command
    try:
        url = await asyncio.to_thread(_send_executor_command, 'voice_stream_url')
        room = os.environ.get('DAN_BROWSER_ROOM', '')
        if not url or not room:
            return
        def update(s):
            if s['state'] not in state.TERMINAL:
                s['screen'] = {'url': url, 'browser_room': room, 'at': state.now()}
        state.change(job_id, update)
    except Exception:
        # Display failure must never cause the underlying operation to be retried.
        pass


class Follower:
    def __init__(self, stage, user_id, room_id, connected_at):
        self.stage = stage
        self.user_id, self.room_id, self.connected_at = user_id, room_id, connected_at
        self.version = stage.version
        self.seen = None

    def update(self, jobs):
        from app.services.voice_stage import safe_image
        stage = self.stage
        if stage.user_id != self.user_id or stage.version != self.version:
            return  # A newer scene wins, including explicit direct voice operations.
        candidates = [j for j in jobs if j.get('user_id') == self.user_id
                      and j.get('origin_room_id') == self.room_id
                      and j.get('state') in {'running', 'awaiting_confirmation', 'completed'}
                      and (j.get('screen') or {}).get('at', '') >= self.connected_at]
        if not candidates:
            return
        job = max(candidates, key=lambda j: j['screen']['at'])
        screen = job['screen']
        key = (job['id'], screen['at'])
        if key == self.seen:
            return
        url = safe_image(screen.get('url'))
        room = screen.get('browser_room')
        if not url or not room or room != job.get('browser_room'):
            return
        self.seen = key
        if stage.image != url:
            stage._apply('ブラウザの画面', image=url)
        stage._external_source = 'browser'
        stage._external_image = url
        stage._external_browser_room = room
        stage._external_job_id = job['id']
        self.version = stage.version
