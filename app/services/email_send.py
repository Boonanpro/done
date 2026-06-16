"""ダンの「追跡付きメール送信」。

送信と同時に external_message_routes に record_outbound して、相手からの返信を
email_poller が「この件の返信だ」と照合できるようにする。これによりダンの能動的
メール送信の返信も、通知タブに返信案として戻ってくる（メール往復が閉じる）。

照合の手がかりを二重に仕込む:
  1. SMTP の Message-ID と X-Dan-Ref ヘッダ（スレッド/ヘッダ照合用）
  2. 本文末尾の不可視気味フッタ `[Ref: REF-XXXX]`（ヘッダが落ちても本文から拾える）

送信は実績のある SMTP(GMAIL_APP_PASSWORD) 経路を使う。
"""
from __future__ import annotations

import logging
import smtplib
import uuid
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


def _make_routing_key() -> str:
    return f"REF-{uuid.uuid4().hex[:10].upper()}"


def send_tracked_email(
    to: str,
    subject: str,
    body: str,
    *,
    user_id: str,
    origin_room_id: str,
    from_name: str = "Done",
    contact_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
) -> dict:
    """メールを送信し、返信照合用に record_outbound する。

    Returns: {"sent": bool, "routing_key": str, "message_id": str, "route_id": str|None}
    Raises: 送信に失敗したら例外（呼び出し側で握る）。
    """
    sender = settings.GMAIL_ADDRESS
    password = settings.GMAIL_APP_PASSWORD
    if not sender or not password:
        raise RuntimeError("GMAIL_ADDRESS/GMAIL_APP_PASSWORD 未設定のためメール送信不可")

    routing_key = _make_routing_key()
    message_id = make_msgid(domain=sender.split("@")[-1] if "@" in sender else None)

    # 本文末尾に控えめな照合フッタ（返信で引用されればヘッダ無しでも拾える）
    full_body = f"{body}\n\n--\n[Ref: {routing_key}]"

    msg = MIMEText(full_body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, sender))
    msg["To"] = to
    msg["Message-ID"] = message_id
    msg["X-Dan-Ref"] = routing_key

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as server:
        server.login(sender, password)
        server.sendmail(sender, [to], msg.as_string())

    logger.info("tracked email sent to=%s ref=%s msgid=%s", to, routing_key, message_id)

    # 送信台帳に記録（失敗しても送信自体は成功しているので握りつぶしてログ）
    route_id = None
    try:
        import asyncio

        from app.services.external_message_routing import get_external_message_routing_service

        svc = get_external_message_routing_service()

        async def _rec():
            return await svc.record_outbound(
                user_id=user_id,
                channel="gmail",
                origin_room_id=origin_room_id,
                external_recipient_id=to,
                external_message_id=message_id,
                routing_key=routing_key,
                contact_id=contact_id,
                campaign_id=campaign_id,
            )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            # 既存ループ内: タスク化（呼び出しが async 文脈の場合）
            route = asyncio.run_coroutine_threadsafe(_rec(), loop).result(timeout=15)
        else:
            route = asyncio.run(_rec())
        route_id = route.get("id") if route else None
    except Exception:
        logger.exception("record_outbound failed (mail was sent)")

    return {
        "sent": True,
        "routing_key": routing_key,
        "message_id": message_id,
        "route_id": route_id,
    }
