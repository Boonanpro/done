# -*- coding: utf-8 -*-
"""Mail-watch checker: does one IMAP look for a `mail` kind watch.

Generalized from scripts/watch_zeirishi_mail.py (which was a hardcoded
one-off for taxdr-kim.com). A watch's spec drives everything:

  spec = {
    "mailbox": "icloud",              # imap_email_service.PROVIDERS のキー (icloud / gmail / gmail2)
    "from": "taxdr-kim.com",          # sender address or domain substring
    "subject_contains": "請求",       # optional extra filter
    "last_uid": 64292,                # advanced after each successful check
    "interval_seconds": 600,
  }

check_mail_watch() is sync (imaplib is sync) — call via asyncio.to_thread.
First run with no last_uid only baselines (records newest UID, wakes no one),
so registering a watch never dredges up already-read mail.
"""
from __future__ import annotations

import email
import logging
import re
from email.header import decode_header
from typing import Any, Dict, List, Tuple

from app.services.imap_email_service import PROVIDERS, connect_mailbox, mailbox_address

logger = logging.getLogger(__name__)

MAX_PER_CHECK = 3
BODY_LIMIT = 2500


def _decode(value) -> str:
    if not value:
        return ""
    out = []
    for s, enc in decode_header(value):
        out.append(s.decode(enc or "utf-8", errors="replace") if isinstance(s, bytes) else s)
    return "".join(out).strip().replace("\r", "")


def _body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                except Exception:
                    pass
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


def _trim_quote(text: str) -> str:
    """Drop quoted history (From: ...) so the wake note carries only the new part."""
    return re.split(r"\n\s*From:\s", text, maxsplit=1)[0].strip()


# 見張れる受信箱 = 受信メール同期と同じ PROVIDERS（icloud / gmail / gmail2）。
MAILBOX_KEYS: Tuple[str, ...] = tuple(PROVIDERS)


def describe_mailboxes() -> str:
    """ツール説明用: 'icloud=xxx@icloud.com / gmail=yyy@gmail.com ...'（.env から）。"""
    return " / ".join(f"{k}={mailbox_address(k) or '未設定'}" for k in MAILBOX_KEYS)


def check_mail_watch(spec: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """Run one check for a mail watch. Returns (updated_spec, new_mails).

    Raises on connection/auth errors — the caller decides retry policy.
    """
    mailbox = (spec.get("mailbox") or "icloud").lower()

    sender_match = (spec.get("from") or "").strip()
    subject_contains = (spec.get("subject_contains") or "").strip()
    last_uid = int(spec.get("last_uid") or 0)

    M = connect_mailbox(mailbox)
    try:
        M.select("INBOX", readonly=True)
        typ, data = M.uid("SEARCH", None, "FROM", sender_match)
        uids = [int(u) for u in (data[0].split() if data and data[0] else [])]

        new_spec = dict(spec)
        if last_uid == 0:
            # Baseline only: never wake on mail that predates the watch.
            new_spec["last_uid"] = max(uids) if uids else 0
            return new_spec, []

        mails: List[Dict[str, str]] = []
        for uid in sorted(u for u in uids if u > last_uid)[:MAX_PER_CHECK]:
            typ, d = M.uid("FETCH", str(uid), "(BODY.PEEK[])")
            if not d or not isinstance(d[0], tuple):
                continue
            msg = email.message_from_bytes(d[0][1])
            subject = _decode(msg.get("Subject"))
            if subject_contains and subject_contains not in subject:
                new_spec["last_uid"] = uid  # matched sender but not subject: consume, don't wake
                continue
            atts = [
                _decode(p.get_filename())
                for p in (msg.walk() if msg.is_multipart() else [])
                if p.get_filename()
            ]
            mails.append({
                "sender": _decode(msg.get("From")),
                "subject": subject,
                "date": _decode(msg.get("Date")),
                "attachments": "、".join(atts) if atts else "なし",
                "body": _trim_quote(_body(msg))[:BODY_LIMIT],
            })
            new_spec["last_uid"] = uid
        return new_spec, mails
    finally:
        try:
            M.logout()
        except Exception:
            pass


def format_mails(mails: List[Dict[str, str]]) -> str:
    blocks = []
    for m in mails:
        blocks.append(
            "--- 受信メール ---\n"
            f"差出人: {m['sender']}\n件名: {m['subject']}\n受信日時: {m['date']}\n"
            f"添付: {m['attachments']}\n本文:\n{m['body']}\n--- ここまで ---"
        )
    return "\n".join(blocks)
