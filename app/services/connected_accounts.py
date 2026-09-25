"""Connected accounts: any provider (google, microsoft, icloud, caldav, ...), any number per user, each usable for one or
more capabilities ('calendar' now; 'mail' etc. later), one of them the default writer per capability.

Replaces calendar_connections (one Google account per user; connecting a second overwrote the first, and the owner's
0aw325171 calendar could never be read beside shub6923, 2026-09-25). Operations: add, reconnect (same account: token
refreshed), replace (another account takes this one's place and its defaults), remove, set default. Tokens are
encrypted at rest; rows returned to callers never carry them.

OAuth `state` is signed (HMAC with the app secret, expiring): it used to be the bare user id, so anyone could have
finished an OAuth flow into someone else's Dan account."""
import base64
import hashlib
import hmac
import json
import time
from typing import Optional

from app.config import settings
from app.services.encryption import decrypt_data, encrypt_data
from app.services.supabase_client import get_supabase_client

TABLE = 'connected_accounts'
PUBLIC = 'id,user_id,provider,account,label,capabilities,default_for,is_active,created_at,updated_at'
STATE_SECONDS = 900


def _db():
    return get_supabase_client().client


def list_accounts(user_id: str, capability: Optional[str] = None, active_only: bool = True) -> list[dict]:
    query = _db().table(TABLE).select(PUBLIC).eq('user_id', user_id)
    if active_only:
        query = query.eq('is_active', True)
    rows = query.order('created_at').execute().data or []
    return [r for r in rows if not capability or capability in (r.get('capabilities') or [])]


def get(user_id: str, account_id: str) -> Optional[dict]:
    rows = _db().table(TABLE).select(PUBLIC).eq('user_id', user_id).eq('id', account_id).execute().data or []
    return rows[0] if rows else None


def find(user_id: str, capability: str, hint: Optional[str]) -> Optional[dict]:
    """The account a request names: its id, the whole address, a part of it (「0aw」), the provider or the label."""
    accounts = list_accounts(user_id, capability)
    if not hint:
        return default_account(user_id, capability)
    hint = str(hint).strip().lower()
    exact = [a for a in accounts if hint in (a['id'], a['account'].lower(), (a.get('label') or '').lower())]
    if exact:
        return exact[0]
    partial = [a for a in accounts if hint in a['account'].lower() or hint in (a.get('label') or '').lower() or hint == a['provider']]
    return partial[0] if len(partial) == 1 else None


def default_account(user_id: str, capability: str) -> Optional[dict]:
    accounts = list_accounts(user_id, capability)
    return next((a for a in accounts if capability in (a.get('default_for') or [])), accounts[0] if accounts else None)


def token(user_id: str, account_id: str) -> Optional[dict]:
    rows = _db().table(TABLE).select('encrypted_token,is_active').eq('user_id', user_id).eq('id', account_id).execute().data or []
    if not rows or not rows[0].get('is_active'):
        return None
    return json.loads(decrypt_data(rows[0]['encrypted_token']))


def update_token(user_id: str, account_id: str, token_data: dict) -> None:
    _db().table(TABLE).update({'encrypted_token': encrypt_data(json.dumps(token_data))}).eq('user_id', user_id).eq('id', account_id).execute()


def save(user_id: str, provider: str, account: str, capabilities: list[str], token_data: dict,
         replace_id: Optional[str] = None, label: Optional[str] = None) -> dict:
    """Add the account, or refresh it when it is already connected. With replace_id, this account takes that one's place:
    that one's defaults move here and it is removed."""
    db = _db()
    existing = db.table(TABLE).select(PUBLIC).eq('user_id', user_id).eq('provider', provider).eq('account', account).execute().data or []
    fields = {'encrypted_token': encrypt_data(json.dumps(token_data)), 'is_active': True}
    if label is not None:
        fields['label'] = label
    if existing:
        row = existing[0]
        fields['capabilities'] = sorted(set(row.get('capabilities') or []) | set(capabilities))
        db.table(TABLE).update(fields).eq('id', row['id']).execute()
        row_id = row['id']
    else:
        inserted = db.table(TABLE).insert({'user_id': user_id, 'provider': provider, 'account': account,
                                           'capabilities': sorted(set(capabilities)), 'default_for': [], **fields}).execute().data
        row_id = inserted[0]['id']
    if replace_id and replace_id != row_id:
        old = get(user_id, replace_id)
        if old:
            for capability in old.get('default_for') or []:
                set_default(user_id, row_id, capability)
            db.table(TABLE).delete().eq('user_id', user_id).eq('id', replace_id).execute()
    for capability in capabilities:   # the first account for a capability is its default writer
        if not any(capability in (a.get('default_for') or []) for a in list_accounts(user_id, capability)):
            set_default(user_id, row_id, capability)
    return get(user_id, row_id)


def set_default(user_id: str, account_id: str, capability: str) -> None:
    db = _db()
    for account in list_accounts(user_id, capability, active_only=False):
        marks = [c for c in (account.get('default_for') or []) if c != capability]
        if account['id'] == account_id:
            marks.append(capability)
        if sorted(marks) != sorted(account.get('default_for') or []):
            db.table(TABLE).update({'default_for': marks}).eq('id', account['id']).execute()


def remove(user_id: str, account_id: str) -> bool:
    """Forget the account. Its defaults pass to another connected account with the same capability."""
    row = get(user_id, account_id)
    if not row:
        return False
    _db().table(TABLE).delete().eq('user_id', user_id).eq('id', account_id).execute()
    for capability in row.get('default_for') or []:
        rest = list_accounts(user_id, capability)
        if rest:
            set_default(user_id, rest[0]['id'], capability)
    return True


# ---- signed OAuth state ---------------------------------------------------------

def _secret() -> bytes:
    return (getattr(settings, 'APP_SECRET_KEY', '') or getattr(settings, 'SECRET_KEY', '') or 'dan').encode()


def sign_state(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps({**payload, 'exp': int(time.time()) + STATE_SECONDS}, separators=(',', ':')).encode()).decode().rstrip('=')
    mac = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f'{body}.{mac}'


def read_state(state: str) -> Optional[dict]:
    try:
        body, mac = state.rsplit('.', 1)
        if not hmac.compare_digest(mac, hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:32]):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
        return payload if payload.get('exp', 0) >= time.time() else None
    except (ValueError, TypeError):
        return None
