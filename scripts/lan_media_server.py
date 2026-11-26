"""家の中の直通: エディターの映像を、Cloudflare を回らずに家の Mac mini から直接読ませる入口。

エディターは dan.paina.info で開くと、映像を1回読むたびにインターネットを回って Mac mini へ来る。
本人の Windows（Wi‑Fi）ではこの待ちが 0.3〜0.7 秒になり、タイムラインで飛ぶたびに止まっていた
（2026-11-18 測り）。家の中にいる時だけ、映像の読み込みをここ（https://dan-home.paina.info、
家の LAN の Mac mini の住所を指す名前）へ向ける。外にいる時は今までどおり dan.paina.info から読む。
どちらを使うかはエディターが自分で決める（frontend/src/components/video-review/media-route.ts）。

- 通すのは、ログイン無しで配っている映像の読み込みだけ（制作の素材・確認用の動画）。ほかは 404。
- 中身はその時のサンドボックス（世代の写しの口）へ直接つなぐ。どの口へ行くかは入口（8100）と同じ決まり
  （app/core/gateway.destination）を使う。入口を通すと、Mac が書き出しで忙しい時にもう1段の Python の
  中継が飢えて、16MB の読みが 0.1〜0.2 秒余計にかかっていた（2026-11-26 測り）。直接の口がつながらない時
  （世代の入れ替わりの途中など）は入口へ回す。どの素材をどう配るかの決まりは向こうの1か所のまま。
- 証明書は Let's Encrypt（DNS の確かめを Cloudflare の鍵で行う）。残り30日を切ったら取り直して
  自分を終える（launchd が新しい証明書で起こし直す）。
- Mac の LAN の住所が変わったら、名前の向き先（Cloudflare の A レコード）を直す。

起動: launchd の com.dan.lan-media（scripts/install_lan_media.py が置く）。
"""
from __future__ import annotations

import asyncio
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import anyio
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services import owner_activity  # noqa: E402

HOST_NAME = 'dan-home.paina.info'
ZONE_NAME = 'paina.info'
STATE = Path.home() / '.dan/lan-media'
LEGO_PATH = STATE / 'lego'
CERT = LEGO_PATH / 'certificates' / f'{HOST_NAME}.crt'
KEY = LEGO_PATH / 'certificates' / f'{HOST_NAME}.key'
ROUTE_FILE = STATE / 'route.json'     # サンドボックスの /home-route が読む（住所と、動いているか）
TOKEN_SERVICE = 'cloudflare_api_token_workers'   # paina.info の DNS を直せる鍵（credentials）
PORT = int(os.environ.get('DAN_LAN_MEDIA_PORT', '443'))

# 通す住所（ログイン無しで配っている、範囲読みの映像だけ）
ALLOWED_PATHS = (
    '/api/v1/production-assets/media',
    '/api/v1/video-review/media',
)
ALLOWED_ORIGINS = {
    'https://dan.paina.info',
    'http://localhost:3000', 'http://localhost:3002', 'http://127.0.0.1:3000', 'http://127.0.0.1:3002',
}
PASS_REQUEST = ('range', 'if-range', 'if-none-match', 'if-modified-since')
PASS_RESPONSE = ('content-type', 'content-length', 'content-range', 'accept-ranges', 'etag', 'last-modified',
                 'x-content-version', 'cache-control')
EXPOSE = 'Content-Range, Content-Length, Accept-Ranges, ETag, Last-Modified, X-Content-Version'


def gateway_base() -> str:
    gen = (Path.home() / '.dan/generations/enabled').exists()
    return f'http://127.0.0.1:{8100 if gen else 8000}'


def upstreams(path: str) -> list[str]:
    """つなぐ先の順番。まずその時のサンドボックスへ直接、だめなら入口（8100）へ。"""
    if os.environ.get('DAN_LAN_MEDIA_UPSTREAM'):
        return [os.environ['DAN_LAN_MEDIA_UPSTREAM']]
    gateway = gateway_base()
    if not gateway.endswith(':8100'):
        return [gateway]
    try:
        from app.core.gateway import destination
        port = destination({'server': ('127.0.0.1', 8100)}, path)
    except Exception as e:  # 世代の記録が読めない時は今までどおり入口へ
        log('direct route unknown:', repr(e)[:200])
        return [gateway]
    return [f'http://127.0.0.1:{port}', gateway]


def log(*parts):
    print(datetime.now().strftime('%m-%d %H:%M:%S'), *parts, flush=True)


def cors_headers(origin: str | None) -> list[tuple[bytes, bytes]]:
    h = [(b'vary', b'Origin'), (b'timing-allow-origin', b'*')]
    if origin and origin in ALLOWED_ORIGINS:
        h += [(b'access-control-allow-origin', origin.encode()),
              (b'access-control-expose-headers', EXPOSE.encode())]
    return h


async def app(scope, receive, send):
    if scope['type'] == 'lifespan':
        while True:
            msg = await receive()
            if msg['type'] == 'lifespan.startup':
                scope.setdefault('state', {})
                app.client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=5, pool=5), trust_env=False,
                                               limits=httpx.Limits(max_connections=64, max_keepalive_connections=32))
                await anyio.to_thread.run_sync(upstreams, ALLOWED_PATHS[0])  # 決まりを先に読み込む（最初の読みを待たせない）
                await send({'type': 'lifespan.startup.complete'})
            elif msg['type'] == 'lifespan.shutdown':
                await app.client.aclose()
                await send({'type': 'lifespan.shutdown.complete'})
                return
    if scope['type'] != 'http':
        return
    headers = {k.decode().lower(): v.decode('latin-1') for k, v in scope['headers']}
    origin = headers.get('origin')
    method = scope['method']
    path = scope['path']

    async def reply(status: int, body: bytes = b'', extra: list | None = None):
        await send({'type': 'http.response.start', 'status': status,
                    'headers': cors_headers(origin) + (extra or []) + [(b'content-length', str(len(body)).encode())]})
        await send({'type': 'http.response.body', 'body': body})

    if method == 'OPTIONS':
        # 公開のページ（dan.paina.info）から家の中の住所を読む時の前もっての問い合わせ（Range と、
        # Chrome の「家の中の機械へのアクセス」の確かめ）に答える
        extra = [(b'access-control-allow-methods', b'GET, HEAD'),
                 (b'access-control-allow-headers', b'Range, If-Range'),
                 (b'access-control-max-age', b'86400')]
        if headers.get('access-control-request-private-network') or headers.get('access-control-request-local-network'):
            extra += [(b'access-control-allow-private-network', b'true'),
                      (b'access-control-allow-local-network', b'true')]
        return await reply(204, extra=extra)
    if path == '/lan/ping':
        body = json.dumps({'ok': True, 'host': HOST_NAME}).encode()
        return await reply(200, body, [(b'content-type', b'application/json'), (b'cache-control', b'no-store')])
    if method not in ('GET', 'HEAD') or path not in ALLOWED_PATHS:
        return await reply(404, b'not here')
    owner_activity.touch()   # the owner is watching: a render on this Mac gives way (envato_shelf)

    query = '?' + scope['query_string'].decode() if scope['query_string'] else ''
    fwd = [(k, v) for k, v in headers.items() if k in PASS_REQUEST]
    res = None
    for base in await anyio.to_thread.run_sync(upstreams, path):
        try:
            res = await app.client.send(app.client.build_request(method, base + path + query, headers=fwd), stream=True)
            break
        except httpx.HTTPError:
            continue
    if res is None:
        return await reply(502, b'upstream unavailable')
    try:
        out = [(k.encode(), v.encode('latin-1')) for k, v in res.headers.items() if k.lower() in PASS_RESPONSE]
        await send({'type': 'http.response.start', 'status': res.status_code, 'headers': cors_headers(origin) + out})
        if method == 'HEAD':
            await send({'type': 'http.response.body', 'body': b''})
            return
        async for chunk in res.aiter_raw():
            await send({'type': 'http.response.body', 'body': chunk, 'more_body': True})
        await send({'type': 'http.response.body', 'body': b''})
    finally:
        with anyio.CancelScope(shield=True):
            await res.aclose()


# --- 名前の向き先と証明書の手入れ ---

def lan_ip() -> str | None:
    for iface in ('en0', 'en1'):
        try:
            ip = subprocess.run(['ipconfig', 'getifaddr', iface], capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            ip = ''
        if ip:
            return ip
    return None


def cloudflare_token() -> str:
    async def get():
        from app.services.credentials_service import get_credentials_service
        from app.services.owner import resolve_owner_user_id
        c = await get_credentials_service().get_credential(resolve_owner_user_id(), TOKEN_SERVICE)
        return (c or {}).get('password') or ''
    return asyncio.run(get())


def cf(token: str, method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request('https://api.cloudflare.com/client/v4' + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b'{}')


def sync_dns(token: str) -> None:
    ip = lan_ip()
    if not ip:
        return
    zones = cf(token, 'GET', f'/zones?name={ZONE_NAME}').get('result') or []
    if not zones:
        log('dns: zone not found'); return
    zid = zones[0]['id']
    recs = cf(token, 'GET', f'/zones/{zid}/dns_records?type=A&name={HOST_NAME}').get('result') or []
    body = {'type': 'A', 'name': HOST_NAME, 'content': ip, 'ttl': 300, 'proxied': False,
            'comment': 'Dan editor: home LAN direct media route (Mac mini)'}
    if not recs:
        r = cf(token, 'POST', f'/zones/{zid}/dns_records', body); log('dns: created', ip, r.get('success'))
    elif recs[0].get('content') != ip:
        r = cf(token, 'PUT', f'/zones/{zid}/dns_records/{recs[0]["id"]}', body); log('dns: moved', recs[0].get('content'), '->', ip, r.get('success'))


def cert_days_left() -> float:
    from cryptography import x509
    c = x509.load_pem_x509_certificate(CERT.read_bytes())
    return (c.not_valid_after_utc - datetime.now(timezone.utc)).total_seconds() / 86400


def obtain_cert(token: str, renew: bool) -> bool:
    env = dict(os.environ, CLOUDFLARE_DNS_API_TOKEN=token)
    args = ['/opt/homebrew/bin/lego', 'run', '--accept-tos', '--path', str(LEGO_PATH), '--dns', 'cloudflare', '--domains', HOST_NAME]
    if renew:
        args += ['--renew-days', '30']
    r = subprocess.run(args, env=env, capture_output=True, text=True, timeout=600)
    log('cert:', 'renew' if renew else 'obtain', r.returncode, (r.stderr or r.stdout)[-300:].replace('\n', ' '))
    return r.returncode == 0


def write_route(alive: bool) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = ROUTE_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps({'base': f'https://{HOST_NAME}' + ('' if PORT == 443 else f':{PORT}'),
                               'alive': alive, 'pid': os.getpid(), 'at': time.time()}))
    tmp.replace(ROUTE_FILE)


def upkeep_loop(stop_server) -> None:
    """10分ごとに名前の向き先を、1日ごとに証明書の残りを確かめる（別の糸で動く）"""
    last_cert = 0.0
    while True:
        try:
            token = cloudflare_token()
            if token:
                sync_dns(token)
                if time.time() - last_cert > 86400:
                    last_cert = time.time()
                    before = CERT.stat().st_mtime
                    if cert_days_left() < 30 and obtain_cert(token, renew=True) and CERT.stat().st_mtime != before:
                        log('cert renewed; restarting to load it')
                        stop_server()
                        return
        except Exception as e:  # 手入れの失敗で配るのを止めない
            log('upkeep error:', repr(e)[:300])
        write_route(True)
        time.sleep(600)


def main():
    import threading
    import uvicorn
    if not CERT.exists():
        token = cloudflare_token()
        if not token or not obtain_cert(token, renew=False):
            log('no certificate; cannot start'); sys.exit(1)
    ctx_ok = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx_ok.load_cert_chain(CERT, KEY)  # 壊れた証明書なら起動前に落ちる
    config = uvicorn.Config(app, host='0.0.0.0', port=PORT, ssl_certfile=str(CERT), ssl_keyfile=str(KEY),
                            log_level='warning', lifespan='on', timeout_keep_alive=30)
    server = uvicorn.Server(config)

    def stop_server():
        server.should_exit = True
    threading.Thread(target=upkeep_loop, args=(stop_server,), daemon=True).start()
    write_route(True)
    try:
        server.run()
    finally:
        write_route(False)


if __name__ == '__main__':
    main()
