"""One stable gateway process with both public backend listeners."""
import asyncio
from pathlib import Path
import socket
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main():
    import uvicorn
    from app.core.job_dispatcher import start
    stop = start()
    sockets = []
    try:
        for port in (9100, 8100):
            sock = socket.socket()
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', port)); sock.listen(2048)
            sockets.append(sock)
        server = uvicorn.Server(uvicorn.Config('app.core.gateway:app', timeout_graceful_shutdown=15))
        await server.serve(sockets=sockets)
    finally:
        stop()
        for sock in sockets: sock.close()


if __name__ == '__main__': asyncio.run(main())
