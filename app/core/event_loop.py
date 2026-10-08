"""The event loop Dan's servers run on (uvicorn --loop app.core.event_loop:new_loop).

On Windows, asyncio closes a listening socket for good when one caller gives up before it is accepted: the accept ends
with ERROR_NETNAME_DELETED and the serving loop treats the caller's failure as the listener's (python/cpython#93821,
still so in 3.13.1). The process keeps running without its port. On 2026-10-07 17:55 the core lost 9000 this way: it
had answered nothing for minutes, the watchdog's health checks timed out and hung up, and the first of them to be
accepted afterwards closed the listener. The watchdog then saw nothing on 9000 and started a second core beside it.
Here such an accept is dropped and the next caller is waited for; every other failure is passed on unchanged.
"""
import asyncio
import logging
import sys

logger = logging.getLogger(__name__)

if sys.platform == 'win32':
    import _overlapped
    from asyncio.windows_events import IocpProactor

    class Proactor(IocpProactor):
        def accept(self, listener):
            answer = self._loop.create_future()
            waiting = []

            def wait():
                f = IocpProactor.accept(self, listener)
                waiting[:] = [f]
                f.add_done_callback(done)

            def done(f):
                if f.cancelled():
                    answer.cancel()
                    return
                exc = f.exception()
                if answer.done():   # serving was stopped while this one arrived
                    if exc is None: f.result()[0].close()
                    return
                if exc is None:
                    answer.set_result(f.result())
                    return
                if getattr(exc, 'winerror', None) == _overlapped.ERROR_NETNAME_DELETED and listener.fileno() != -1:
                    logger.warning('a caller gave up before it was accepted on %s; still listening', listener.getsockname())
                    try:
                        wait()
                        return
                    except OSError as failed:
                        exc = failed
                answer.set_exception(exc)

            answer.add_done_callback(lambda a: a.cancelled() and waiting[0].cancel())
            wait()
            return answer


def new_loop():
    if sys.platform != 'win32':
        return asyncio.new_event_loop()
    return asyncio.ProactorEventLoop(Proactor())
