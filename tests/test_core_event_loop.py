"""A server keeps its port when callers give up before they are accepted (app/core/event_loop.py)."""
import asyncio
import socket
import struct
import sys
import threading
import time

import pytest

from app.core.event_loop import new_loop

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='the fault is in the Windows event loop')


def _answers(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=2) as s:
            s.sendall(b'hi')
            return s.recv(10) == b'ok'
    except OSError:
        return False


def _callers_that_give_up(port):
    first = socket.create_connection(('127.0.0.1', port))   # takes the accept that is already waiting
    for _ in range(5):   # these wait in the queue and hang up, as a timed-out health check does
        s = socket.create_connection(('127.0.0.1', port))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('hh', 1, 0))
        s.close()
    first.close()


async def _serve_through_a_busy_spell():
    async def handle(reader, writer):
        if await reader.read(10):
            writer.write(b'ok')
            await writer.drain()
        writer.close()
    server = await asyncio.start_server(handle, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    callers = threading.Thread(target=_callers_that_give_up, args=(port,))
    callers.start()
    time.sleep(1)   # the loop answers nothing while the callers come and go
    callers.join()
    await asyncio.sleep(0.5)
    answered = await asyncio.get_running_loop().run_in_executor(None, _answers, port)
    server.close()
    await server.wait_closed()
    return answered


def test_port_survives_callers_that_gave_up():
    loop = new_loop()
    try:
        assert loop.run_until_complete(_serve_through_a_busy_spell())
    finally:
        loop.close()


def test_stock_loop_loses_the_port():
    """The fault this guards against; when Python fixes it this fails and app/core/event_loop.py can go."""
    loop = asyncio.ProactorEventLoop()
    loop.set_exception_handler(lambda loop, context: None)
    try:
        assert not loop.run_until_complete(_serve_through_a_busy_spell())
    finally:
        loop.close()
