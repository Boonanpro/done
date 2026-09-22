import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import voice_credentials as auth


def token(exp):
    return 'x.' + base64.urlsafe_b64encode(json.dumps({'exp': exp}).encode()).decode().rstrip('=') + '.x'


class CredentialsTest(unittest.IsolatedAsyncioTestCase):
    async def test_valid_token_does_not_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'auth.json'
            auth.save_credentials(path, {'token': token(9999999999)})
            with patch.object(auth.httpx, 'AsyncClient', side_effect=AssertionError('unneeded network')):
                self.assertEqual((await auth.load_credentials(path, 'http://core'))['token'], token(9999999999))

    async def test_expired_without_refresh_needs_pairing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'auth.json'
            auth.save_credentials(path, {'token': token(0)})
            with self.assertRaises(auth.PairingExpired):
                await auth.load_credentials(path, 'http://core')

    async def test_refresh_persists_rotated_pair_and_preserves_on_failure(self):
        client_class = httpx.AsyncClient
        for status in (200, 401, 503):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'auth.json'
                original = {'token': token(0), 'refresh_token': 'old'}
                auth.save_credentials(path, original)
                def handle(request):
                    self.assertEqual(json.loads(request.content), {'refresh_token': 'old'})
                    return httpx.Response(status, json={'access_token': token(9999999999), 'refresh_token': 'new'})
                with patch.object(auth.httpx, 'AsyncClient', lambda **kw: client_class(transport=httpx.MockTransport(handle), **kw)):
                    if status == 200:
                        result = await auth.load_credentials(path, 'http://core')
                        self.assertEqual(result['refresh_token'], 'new')
                        self.assertEqual(json.loads(path.read_text()), result)
                    else:
                        with self.assertRaises(auth.PairingExpired if status == 401 else httpx.HTTPStatusError):
                            await auth.load_credentials(path, 'http://core')
                        self.assertEqual(json.loads(path.read_text()), original)

    def test_expiry_margin_and_malformed_token(self):
        self.assertTrue(auth.expires_soon(token(1100), now=1000))
        self.assertFalse(auth.expires_soon(token(1500), now=1000))
        self.assertTrue(auth.expires_soon('broken'))


if __name__ == '__main__': unittest.main()
