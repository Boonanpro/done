"""Shared pollers execute room work in the current release, never their old code."""
import asyncio
import json
import logging
import os
import httpx
from app.core import generations as G


def remote_required():
    from app.services.room_feed import in_core_process
    return (in_core_process() and not os.environ.get('DAN_GENERATION')
            and (G.ROOT / 'enabled').exists() and bool(G.read('active')))


async def relay(arguments):
    room = arguments['room_id']
    reservation = await asyncio.to_thread(G.reserve_room, room)
    if not reservation:
        raise RuntimeError('No active release for background room work')
    try:
        port = reservation[0]['core']
        if port == 9000:
            raise RuntimeError('Background work cannot return to the shared core')
        logging.getLogger(__name__).info('Room %s: shared background work -> release %s', room, reservation[0].get('id'))
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10), trust_env=False) as client:
            # No retry: a lost response does not mean the work was not accepted.
            async with client.stream('POST', f'http://127.0.0.1:{port}/api/v1/chat/internal/agent/turn', json=arguments) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.strip():
                        yield json.loads(line)
    finally:
        G.release_room(room, reservation[1])
