"""The send stream cleans up even when the reply is cut mid-way (2026-10-14).

When the client goes away, the web server stops the stream's generator at its next pause and never resumes it. The
finally block yielded the closing "done" event before removing the room's entry in the registry of running work, so the
generator stopped there: /active kept answering "Dan is working" for good (seen for 6+ minutes after the answer), and
the screen kept its stop button. The cleanup has to come before any yield in that finally."""
import ast
from pathlib import Path

import anyio

ROOT = Path(__file__).resolve().parents[1]


def _send_stream_finally():
    tree = ast.parse((ROOT / 'app/api/chat_routes.py').read_text(encoding='utf-8'))
    gen = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'generate_stream'
               and any(isinstance(c, ast.Call) and getattr(c.func, 'attr', '') == 'unregister' for c in ast.walk(n)))
    return max((t for t in ast.walk(gen) if isinstance(t, ast.Try) and t.finalbody), key=lambda t: len(t.finalbody)).finalbody


def test_the_room_is_released_before_the_last_event_is_sent():
    body = _send_stream_finally()
    def first(pred):
        return next(i for i, stmt in enumerate(body) if any(pred(n) for n in ast.walk(stmt)))
    released = first(lambda n: isinstance(n, ast.Call) and getattr(n.func, 'attr', '') == 'unregister'
                     and getattr(n.func.value, 'id', '') == 'CancellationRegistry')
    yielded = first(lambda n: isinstance(n, (ast.Yield, ast.YieldFrom)))
    assert released < yielded


def test_why_the_order_matters():
    """The web server's way of stopping a stream whose client left: what runs after a yield in finally never runs."""
    ran = []

    async def stream():
        try:
            yield 'start'
            await anyio.sleep(10)
        finally:
            ran.append('before the last event')
            yield 'done'
            ran.append('after the last event')

    async def main():
        gen = stream()
        async def send_all():
            async for _ in gen:
                await anyio.sleep(0)
        async with anyio.create_task_group() as tg:
            tg.start_soon(send_all)
            await anyio.sleep(0.05)
            tg.cancel_scope.cancel()

    anyio.run(main)
    assert ran == ['before the last event']
