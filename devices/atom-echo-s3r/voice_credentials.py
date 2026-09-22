"""Renew the voice worker's paired credentials without browser interaction."""
import base64
import asyncio
import json
import time
from pathlib import Path

import httpx

credential_lock = asyncio.Lock()


class PairingExpired(Exception):
    pass


def expires_soon(token, now=None):
    try:
        part = token.split('.')[1]
        expiry = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))['exp']
        return expiry < (time.time() if now is None else now) + 300
    except (ValueError, KeyError, IndexError, TypeError):
        return True


def save_credentials(path: Path, credentials):
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps(credentials), encoding='utf-8')
    temporary.replace(path)


async def load_credentials(path: Path, base: str):
    async with credential_lock:
        return await _load_credentials(path, base)


async def _load_credentials(path: Path, base: str):
    credentials = json.loads(path.read_text(encoding='utf-8'))
    if not expires_soon(credentials.get('token', '')):
        return credentials
    if not credentials.get('refresh_token'):
        raise PairingExpired()
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(base + '/api/v1/chat/refresh', json={
            'refresh_token': credentials['refresh_token'],
        })
    if response.status_code == 401:
        raise PairingExpired()
    response.raise_for_status()
    data = response.json()
    renewed = {'token': data['access_token'], 'refresh_token': data['refresh_token']}
    save_credentials(path, renewed)
    return renewed
