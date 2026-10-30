"""Drive requests for the authorized Docs integration. Never log OAuth material."""
import json
from pathlib import Path
import time
import httpx

_tokens = {}

def request(account, method, path, body=None, params=None):
    from app.config import settings
    from app.services.encryption import decrypt_data
    if not account.replace('_', '').isalnum():
        raise ValueError('Invalid account')
    cached = _tokens.get(account)
    with httpx.Client(timeout=30, trust_env=False) as client:
        if not cached or cached[1] < time.time():
            saved = json.loads(decrypt_data((Path.home()/'.dan'/f'gdrive_{account}_token.enc').read_text()))
            response = client.post('https://oauth2.googleapis.com/token', data={
                'refresh_token': saved['refresh_token'], 'client_id': settings.gmail_client_id,
                'client_secret': settings.gmail_client_secret, 'grant_type': 'refresh_token'})
            response.raise_for_status()
            token = response.json()
            cached = (token['access_token'], time.time() + token.get('expires_in', 3600) - 120)
            _tokens[account] = cached
        response = client.request(method, 'https://www.googleapis.com/drive/v3/' + path,
                                  headers={'Authorization': 'Bearer ' + cached[0]}, json=body, params=params)
        response.raise_for_status()
        return response.json() if response.content else {}

def comments(account, file_id, since=None):
    params = {'fields': '*', 'pageSize': 100, 'includeDeleted': 'true'}
    if since: params['startModifiedTime'] = since
    result = []
    while True:
        page = request(account, 'GET', f'files/{file_id}/comments', params=params)
        result.extend(page.get('comments', []))
        if not page.get('nextPageToken'): return result
        params['pageToken'] = page['nextPageToken']
