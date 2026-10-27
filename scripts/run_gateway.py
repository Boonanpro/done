"""One stable gateway process with both public backend listeners."""
import asyncio
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main():
    import uvicorn
    from app.core.job_dispatcher import start
    stop = start()
    servers = [uvicorn.Server(uvicorn.Config('app.core.gateway:app', host='127.0.0.1', port=port,
                                            timeout_graceful_shutdown=15)) for port in (9100, 8100)]
    try:
        await asyncio.gather(*(s.serve() for s in servers))
    finally:
        stop()


if __name__ == '__main__': asyncio.run(main())
