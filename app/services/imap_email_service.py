"""
IMAP Email Service: Gmail / iCloud から IMAP で新着メールを取得し、
detection_service 経由で dan-notion inbox に投入する。

state は data/email_sync_state.json に保存 (provider別の last_uid)。
ATTACHMENT_STORAGE_PATH 配下に添付ファイルを保存。
"""
import imaplib
import email
import json
import logging
import re
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

from app.config import settings
from app.services.message_detection import get_detection_service
from app.models.detection_schemas import MessageSource

logger = logging.getLogger(__name__)

PROVIDERS = {
    "gmail": {
        "host": "imap.gmail.com",
        "port": 993,
        "address_attr": "GMAIL_ADDRESS",
        "password_attr": "GMAIL_APP_PASSWORD",
        "source": MessageSource.GMAIL,
    },
    "icloud": {
        "host": "imap.mail.me.com",
        "port": 993,
        "address_attr": "ICLOUD_ADDRESS",
        "password_attr": "ICLOUD_APP_PASSWORD",
        "source": MessageSource.GMAIL,  # detection_schemas に icloud_mail が無いため一旦 gmail として扱う
    },
}

STATE_FILE = Path("D:/done/data/email_sync_state.json")
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
ATTACHMENT_DIR = Path(settings.ATTACHMENT_STORAGE_PATH if hasattr(settings, "ATTACHMENT_STORAGE_PATH") else "./data/attachments")
ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _decode_mime_header(value: Optional[str]) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for s, enc in parts:
        if isinstance(s, bytes):
            try:
                out.append(s.decode(enc or "utf-8", errors="replace"))
            except Exception:
                out.append(s.decode("utf-8", errors="replace"))
        else:
            out.append(s)
    return "".join(out).strip()


def _extract_body(msg: email.message.Message) -> str:
    """text/plain を優先、無ければ text/html を text 化"""
    if msg.is_multipart():
        # plain
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                except Exception:
                    pass
        # html fallback
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                    return re.sub(r"<[^>]+>", "", html)
                except Exception:
                    pass
    else:
        try:
            return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            return msg.get_payload() or ""
    return ""


def _extract_and_save_attachments(msg: email.message.Message, message_id: str) -> list[dict]:
    """添付を ATTACHMENT_DIR に保存して metadata を返す。"""
    out = []
    if not msg.is_multipart():
        return out
    for part in msg.walk():
        cd = str(part.get("Content-Disposition", ""))
        if "attachment" not in cd and not part.get_filename():
            continue
        filename = _decode_mime_header(part.get_filename() or "")
        if not filename:
            continue
        try:
            data = part.get_payload(decode=True)
            if not data:
                continue
            safe_name = re.sub(r"[^\w\.\-]", "_", filename)
            target = ATTACHMENT_DIR / f"{message_id}_{safe_name}"
            target.write_bytes(data)
            out.append({
                "filename": filename,
                "size": len(data),
                "content_type": part.get_content_type(),
                "storage_path": str(target),
            })
        except Exception:
            logger.exception("attachment save failed: %s", filename)
    return out


def _connect(provider_key: str) -> Optional[imaplib.IMAP4_SSL]:
    cfg = PROVIDERS[provider_key]
    addr = getattr(settings, cfg["address_attr"], "") or ""
    pw = getattr(settings, cfg["password_attr"], "") or ""
    if not addr or not pw:
        logger.info("imap %s: not configured", provider_key)
        return None
    M = imaplib.IMAP4_SSL(cfg["host"], cfg["port"])
    pw_clean = pw.replace(" ", "").replace("-", "")  # iCloud 表示は xxxx-xxxx 形式だが認証時は連結
    try:
        # 元のフォーマットでも試す: iCloud は - を含めても通る場合あり
        try:
            M.login(addr, pw)
        except imaplib.IMAP4.error:
            M.login(addr, pw_clean)
    except imaplib.IMAP4.error as e:
        logger.error("imap %s login failed: %s", provider_key, e)
        try: M.logout()
        except Exception: pass
        return None
    return M


async def fetch_provider(user_id: str, provider_key: str, max_messages: int = 30) -> dict:
    """
    指定 provider から新着メールを取得し、dan-notion inbox に投入。

    Returns: {"provider": ..., "fetched": N, "errors": [...], "last_uid": ...}
    """
    cfg = PROVIDERS[provider_key]
    state = _load_state()
    last_uid = (state.get(provider_key) or {}).get("last_uid", 0)

    M = _connect(provider_key)
    if not M:
        return {"provider": provider_key, "fetched": 0, "errors": ["not configured or login failed"], "last_uid": last_uid}

    detection = get_detection_service()
    fetched = 0
    errors: list[str] = []
    new_last_uid = last_uid

    try:
        M.select("INBOX")
        # last_uid より大きい UID を取得
        search_query = f"UID {last_uid + 1}:*" if last_uid > 0 else "ALL"
        typ, data = M.uid("SEARCH", None, search_query)
        if typ != "OK" or not data or not data[0]:
            return {"provider": provider_key, "fetched": 0, "errors": [], "last_uid": last_uid}

        uids = data[0].split()
        # 初回 ALL 取得時は最新 max_messages 件のみに限定 (履歴ぜんぶ流入を防ぐ)
        if last_uid == 0:
            uids = uids[-max_messages:]
        else:
            uids = uids[:max_messages]

        for raw_uid in uids:
            uid = int(raw_uid.decode())
            try:
                typ, msg_data = M.uid("FETCH", str(uid).encode(), "(RFC822)")
                if typ != "OK" or not msg_data:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                subject = _decode_mime_header(msg.get("Subject"))
                from_addr = _decode_mime_header(msg.get("From"))
                date_str = msg.get("Date") or ""
                msg_id_header = msg.get("Message-ID") or f"{provider_key}-uid-{uid}"
                body = _extract_body(msg)
                attachments = _extract_and_save_attachments(msg, msg_id_header.replace("<", "").replace(">", "").replace("/", "_")[:80])

                await detection.detect_message(
                    user_id=user_id,
                    source=cfg["source"],
                    content=body,
                    source_id=msg_id_header,
                    subject=subject,
                    sender_info={"from": from_addr, "date": date_str, "provider": provider_key},
                    metadata={"attachments": attachments, "uid": uid, "provider": provider_key},
                )
                fetched += 1
                new_last_uid = max(new_last_uid, uid)
            except Exception as e:
                errors.append(f"uid={uid}: {e!r}")
                logger.exception("imap %s fetch uid=%s failed", provider_key, uid)
    finally:
        try: M.close()
        except Exception: pass
        try: M.logout()
        except Exception: pass

    # state 更新
    state[provider_key] = {
        "last_uid": new_last_uid,
        "last_synced_at": datetime.now(timezone.utc).isoformat(),
        "address": getattr(settings, cfg["address_attr"], ""),
    }
    _save_state(state)

    logger.info("imap %s sync done: fetched=%d, last_uid=%d", provider_key, fetched, new_last_uid)
    return {"provider": provider_key, "fetched": fetched, "errors": errors, "last_uid": new_last_uid}


async def fetch_all(user_id: str, max_messages_per_provider: int = 30) -> list[dict]:
    """設定済みの全 provider を順次 fetch"""
    out = []
    for key in PROVIDERS:
        out.append(await fetch_provider(user_id, key, max_messages_per_provider))
    return out
