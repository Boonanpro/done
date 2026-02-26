"""
SSL WebSocket proxy for mobile access.

Runs on port 8443 with SSL, proxies WebSocket connections to
the main FastAPI server on port 8000 (HTTP).

This solves the mixed-content problem:
  HTTPS frontend (phone) → wss://host:8443 → ws://127.0.0.1:8000
"""

import ssl
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CERT_FILE = Path("D:/done/frontend/certificates/localhost.pem")
KEY_FILE = Path("D:/done/frontend/certificates/localhost-key.pem")
PROXY_PORT = 8443
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Pipe data from reader to writer until EOF."""
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _handle_client(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter):
    """Handle an incoming SSL connection by proxying to the backend."""
    try:
        backend_reader, backend_writer = await asyncio.open_connection(
            BACKEND_HOST, BACKEND_PORT
        )
    except Exception as e:
        logger.error("Cannot connect to backend: %s", e)
        client_writer.close()
        return

    # Pipe both directions
    t1 = asyncio.create_task(_pipe(client_reader, backend_writer))
    t2 = asyncio.create_task(_pipe(backend_reader, client_writer))

    await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)

    # Cancel the other task
    t1.cancel()
    t2.cancel()


async def start_wss_proxy():
    """Start the SSL WebSocket proxy server on port 8443."""
    if not CERT_FILE.exists() or not KEY_FILE.exists():
        logger.warning("SSL certificates not found, WSS proxy disabled")
        return None

    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(str(CERT_FILE), str(KEY_FILE))

    server = await asyncio.start_server(
        _handle_client,
        host="0.0.0.0",
        port=PROXY_PORT,
        ssl=ssl_ctx,
    )

    logger.info("WSS proxy listening on 0.0.0.0:%d → %s:%d", PROXY_PORT, BACKEND_HOST, BACKEND_PORT)
    return server
