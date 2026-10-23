"""保存済みパスワードを本人の画面にだけ全文で出す（パスキーで本人確認）。

ダン（AI）が get_credentials で受け取るパスワードは先頭2文字以外を伏せる。
全文が会話の記録・AIサービスへの送信・通知に残らないようにするためで、この方針は変えない。
本人が全文を見たい時は、Done の /vault 画面からこのサービスを通して取り出す。

- 本人確認は WebAuthn（パスキー）。PC は Windows の PIN、スマホは指紋・顔認証。
  userVerification を必須にし、認証器が UV フラグを立てた時だけ通す。
- 端末の登録は「登録受付の時間」だけ。最初の1台は PC のスクリプト
  （scripts/secret_vault_enroll.py）で開け、2台目以降は登録済みの端末で本人確認して開ける。
- 表示・登録・削除のたびに記録（reveal_log.jsonl）を残し、本人のスマホに通知する。

公開鍵・記録は PC のローカル（.data/secret_vault/）に置く。パスワード本体は従来どおり
credentials_service の暗号化保管庫にあり、ここには保存しない。
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

logger = logging.getLogger(__name__)

# パスキーを使ってよいサイト（RP ID）。本人が Done を開くのはこの2か所。
ALLOWED_RP_IDS = {
    h.strip() for h in os.getenv("DAN_VAULT_RP_IDS", "dan.paina.info,localhost").split(",") if h.strip()
}
CHALLENGE_TTL = 180  # 秒
ENROLL_WINDOW_MINUTES = 10
MAX_FAILURES = 5
LOCK_SECONDS = 600

FLAG_UP = 0x01
FLAG_UV = 0x04
FLAG_AT = 0x40

_lock = threading.Lock()
_challenges: dict[str, dict[str, Any]] = {}
_failures: list[float] = []


class VaultError(Exception):
    """本人に見せてよい理由つきの失敗。"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- 保存場所

def _data_dir() -> Path:
    override = os.getenv("DAN_SECRET_VAULT_DIR")
    path = Path(override) if override else Path(__file__).resolve().parents[2] / ".data" / "secret_vault"
    path.mkdir(parents=True, exist_ok=True)
    ignore = path / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8")  # 端末の記録や表示の記録をリポジトリに入れない
    return path


def _read_json(name: str, default: Any) -> Any:
    path = _data_dir() / name
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.warning("secret_vault: %s を読めません", path)
        return default


def _write_json(name: str, data: Any) -> None:
    path = _data_dir() / name
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_passkeys() -> list[dict[str, Any]]:
    return _read_json("passkeys.json", [])


def _save_passkeys(items: list[dict[str, Any]]) -> None:
    _write_json("passkeys.json", items)


def log_event(event: str, **fields: Any) -> None:
    row = {"at": _now().isoformat(), "event": event, **fields}
    with open(_data_dir() / "reveal_log.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def recent_events(limit: int = 20) -> list[dict[str, Any]]:
    path = _data_dir() / "reveal_log.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return out


# ---------------------------------------------------------------- 登録受付の時間

def enroll_open_until() -> Optional[datetime]:
    data = _read_json("enroll.json", {})
    until = data.get("until")
    if not until:
        return None
    try:
        dt = datetime.fromisoformat(until)
    except ValueError:
        return None
    return dt if dt > _now() else None


def open_enroll_window(opened_by: str, minutes: int = ENROLL_WINDOW_MINUTES) -> datetime:
    until = _now() + timedelta(minutes=minutes)
    _write_json("enroll.json", {"until": until.isoformat(), "opened_by": opened_by})
    log_event("enroll_open", opened_by=opened_by, until=until.isoformat())
    return until


def close_enroll_window() -> None:
    _write_json("enroll.json", {})


# ---------------------------------------------------------------- 補助

def b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64u_decode(text: str) -> bytes:
    text = (text or "").strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _check_failures() -> None:
    cutoff = time.time() - LOCK_SECONDS
    with _lock:
        _failures[:] = [t for t in _failures if t > cutoff]
        if len(_failures) >= MAX_FAILURES:
            raise VaultError("本人確認の失敗が続いたので、10分間止めています。", status=429)


def _record_failure() -> None:
    with _lock:
        _failures.append(time.time())


def rp_id_for_origin(origin: str) -> str:
    """ブラウザの origin から RP ID を決める。許可した場所以外は断る。"""
    parsed = urlparse(origin or "")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_RP_IDS:
        raise VaultError(f"この場所（{host or '不明'}）からはパスワードを表示できません。", status=403)
    if parsed.scheme != "https" and host != "localhost":
        raise VaultError("https で開いてください。", status=403)
    return host


def new_challenge(user_id: str, purpose: str, rp_id: str, origin: str, target: str = "") -> str:
    challenge = b64u_encode(secrets.token_bytes(32))
    now = time.time()
    with _lock:
        for key in [k for k, v in _challenges.items() if v["expires"] < now]:
            _challenges.pop(key, None)
        _challenges[challenge] = {
            "user_id": user_id,
            "purpose": purpose,
            "rp_id": rp_id,
            "origin": origin,
            "target": target,
            "expires": now + CHALLENGE_TTL,
        }
    return challenge


def _take_challenge(challenge: str, user_id: str, purpose: str, target: str = "") -> dict[str, Any]:
    with _lock:
        entry = _challenges.pop(challenge, None)
    if (
        not entry
        or entry["expires"] < time.time()
        or entry["user_id"] != user_id
        or entry["purpose"] != purpose
        or entry["target"] != target
    ):
        raise VaultError("確認の期限が切れました。もう一度押してください。")
    return entry


def _check_client_data(client_data_json: bytes, expected_type: str, challenge: str, origin: str) -> None:
    try:
        client = json.loads(client_data_json.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise VaultError("本人確認の応答を読めませんでした。") from exc
    if client.get("type") != expected_type:
        raise VaultError("本人確認の応答の種類が違います。")
    if client.get("challenge") != challenge:
        raise VaultError("本人確認の応答が、この操作のものではありません。")
    if client.get("origin") != origin:
        raise VaultError("本人確認をした場所が違います。")


def _check_auth_data(auth_data: bytes, rp_id: str) -> tuple[int, int]:
    if len(auth_data) < 37:
        raise VaultError("本人確認の応答が短すぎます。")
    if auth_data[:32] != hashlib.sha256(rp_id.encode("utf-8")).digest():
        raise VaultError("本人確認をしたサイトが違います。")
    flags = auth_data[32]
    if not flags & FLAG_UP:
        raise VaultError("端末の操作が確認できませんでした。")
    if not flags & FLAG_UV:
        raise VaultError("PIN・指紋・顔認証のどれかで本人確認してください。")
    sign_count = int.from_bytes(auth_data[33:37], "big")
    return flags, sign_count


def _load_public_key(spki_b64: str):
    return serialization.load_der_public_key(b64u_decode(spki_b64))


def _verify_signature(public_key, alg: int, signature: bytes, data: bytes) -> None:
    try:
        if isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(signature, data, ec.ECDSA(hashes.SHA256()))
        elif isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(signature, data, padding.PKCS1v15(), hashes.SHA256())
        elif isinstance(public_key, ed25519.Ed25519PublicKey):
            public_key.verify(signature, data)
        else:
            raise VaultError("この端末の鍵の種類には対応していません。")
    except InvalidSignature as exc:
        raise VaultError("本人確認の署名が合いません。", status=403) from exc


def _public_key_raw_parts(public_key) -> list[bytes]:
    """登録時、送られた公開鍵が認証器の応答に含まれる鍵と同じかを照らすための値。"""
    if isinstance(public_key, ec.EllipticCurvePublicKey):
        nums = public_key.public_numbers()
        size = (public_key.curve.key_size + 7) // 8
        return [nums.x.to_bytes(size, "big"), nums.y.to_bytes(size, "big")]
    if isinstance(public_key, rsa.RSAPublicKey):
        n = public_key.public_numbers().n
        return [n.to_bytes((n.bit_length() + 7) // 8, "big")]
    if isinstance(public_key, ed25519.Ed25519PublicKey):
        return [public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)]
    raise VaultError("この端末の鍵の種類には対応していません。")


# ---------------------------------------------------------------- 登録

def registration_options(user_id: str, origin: str, user_name: str) -> dict[str, Any]:
    if not enroll_open_until():
        raise VaultError("今は端末の登録を受け付けていません。登録済みの端末で「端末を追加」を押してください。", status=403)
    rp_id = rp_id_for_origin(origin)
    challenge = new_challenge(user_id, "register", rp_id, origin)
    return {
        "challenge": challenge,
        "rp": {"id": rp_id, "name": "Done"},
        "user": {"id": b64u_encode(user_id.encode("utf-8")), "name": user_name, "displayName": user_name},
        "excludeCredentials": [p["credential_id"] for p in load_passkeys() if p.get("rp_id") == rp_id],
    }


def finish_registration(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _check_failures()
    try:
        entry = _take_challenge(payload.get("challenge", ""), user_id, "register")
        if not enroll_open_until():
            raise VaultError("登録の受付時間が終わりました。", status=403)
        client_data = b64u_decode(payload["client_data_json"])
        auth_data = b64u_decode(payload["authenticator_data"])
        _check_client_data(client_data, "webauthn.create", payload["challenge"], entry["origin"])
        flags, sign_count = _check_auth_data(auth_data, entry["rp_id"])
        if not flags & FLAG_AT:
            raise VaultError("端末の鍵が応答に含まれていません。")
        cred_len = int.from_bytes(auth_data[53:55], "big")
        cred_id = auth_data[55:55 + cred_len]
        if b64u_encode(cred_id) != payload.get("credential_id"):
            raise VaultError("端末の鍵の番号が合いません。")
        cose_key = auth_data[55 + cred_len:]
        public_key = _load_public_key(payload["public_key"])
        if not all(part in cose_key for part in _public_key_raw_parts(public_key)):
            raise VaultError("端末の鍵が応答の中身と合いません。")
    except VaultError:
        _record_failure()
        raise
    except (KeyError, ValueError) as exc:
        _record_failure()
        raise VaultError("本人確認の応答を読めませんでした。") from exc

    label = (payload.get("label") or "").strip()[:40] or "名前のない端末"
    item = {
        "credential_id": payload["credential_id"],
        "public_key": payload["public_key"],
        "alg": int(payload.get("alg") or -7),
        "rp_id": entry["rp_id"],
        "user_id": user_id,
        "label": label,
        "sign_count": sign_count,
        "created_at": _now().isoformat(),
        "last_used_at": None,
    }
    with _lock:
        items = [p for p in load_passkeys() if p["credential_id"] != item["credential_id"]]
        items.append(item)
        _save_passkeys(items)
    log_event("register", label=label, rp_id=entry["rp_id"])
    return {"label": label, "rp_id": entry["rp_id"]}


# ---------------------------------------------------------------- 本人確認

def assertion_options(user_id: str, origin: str, purpose: str, target: str = "") -> dict[str, Any]:
    _check_failures()
    rp_id = rp_id_for_origin(origin)
    allowed = [p["credential_id"] for p in load_passkeys() if p.get("rp_id") == rp_id and p.get("user_id") == user_id]
    if not allowed:
        raise VaultError("この画面では、まだ端末が登録されていません。", status=409)
    challenge = new_challenge(user_id, purpose, rp_id, origin, target)
    return {"challenge": challenge, "rpId": rp_id, "allowCredentials": allowed}


def verify_assertion(user_id: str, payload: dict[str, Any], purpose: str, target: str = "") -> dict[str, Any]:
    """本人確認の応答を確かめ、使った端末の記録を返す。"""
    _check_failures()
    try:
        entry = _take_challenge(payload.get("challenge", ""), user_id, purpose, target)
        cred_id = payload.get("credential_id", "")
        passkeys = load_passkeys()
        passkey = next(
            (p for p in passkeys if p["credential_id"] == cred_id and p.get("user_id") == user_id), None
        )
        if not passkey or passkey.get("rp_id") != entry["rp_id"]:
            raise VaultError("登録されていない端末です。", status=403)
        client_data = b64u_decode(payload["client_data_json"])
        auth_data = b64u_decode(payload["authenticator_data"])
        signature = b64u_decode(payload["signature"])
        _check_client_data(client_data, "webauthn.get", payload["challenge"], entry["origin"])
        _flags, sign_count = _check_auth_data(auth_data, entry["rp_id"])
        public_key = _load_public_key(passkey["public_key"])
        _verify_signature(public_key, passkey.get("alg", -7), signature, auth_data + hashlib.sha256(client_data).digest())
        if sign_count and passkey.get("sign_count") and sign_count <= passkey["sign_count"]:
            raise VaultError("この端末の鍵が複製された疑いがあるので止めました。", status=403)
    except VaultError:
        _record_failure()
        raise
    except (KeyError, ValueError) as exc:
        _record_failure()
        raise VaultError("本人確認の応答を読めませんでした。") from exc

    with _lock:
        items = load_passkeys()
        for p in items:
            if p["credential_id"] == cred_id:
                p["sign_count"] = sign_count
                p["last_used_at"] = _now().isoformat()
        _save_passkeys(items)
    return passkey


def delete_passkey(credential_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        items = load_passkeys()
        removed = next((p for p in items if p["credential_id"] == credential_id), None)
        _save_passkeys([p for p in items if p["credential_id"] != credential_id])
    return removed


async def notify_owner(user_id: str, body: str) -> None:
    """本人のスマホに知らせる。失敗しても表示そのものは止めない。"""
    try:
        from app.services.push_service import get_push_service

        await get_push_service().notify_room(
            room_id=f"user:{user_id}", exclude_type="ai", title="Done パスワード", body=body, url="/vault"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("secret_vault notify failed: %s", exc)
