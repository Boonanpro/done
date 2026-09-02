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
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid
from pathlib import Path
from typing import Optional, Sequence

from app.config import settings

logger = logging.getLogger(__name__)


def _make_routing_key() -> str:
    return f"REF-{uuid.uuid4().hex[:10].upper()}"


# 送信アカウント。相手が普段やり取りしているアドレスから出すために選べるようにする。
SEND_ACCOUNTS = {
    "gmail": {
        "address_attr": "GMAIL_ADDRESS",
        "password_attr": "GMAIL_APP_PASSWORD",
        "host": "smtp.gmail.com",
        "port": 465,
        "ssl": True,
        # Gmail は SMTP 送信分を自動で「送信済み」に保存するので APPEND 不要。
        "imap_host": None,
        "sent_box": None,
    },
    "gmail2": {
        # 0aw325171@gmail.com（note / イツキ関連の連絡で使うサブアドレス）
        "address_attr": "GMAIL2_ADDRESS",
        "password_attr": "GMAIL2_APP_PASSWORD",
        "host": "smtp.gmail.com",
        "port": 465,
        "ssl": True,
        "imap_host": None,
        "sent_box": None,
    },
    "icloud": {
        "address_attr": "ICLOUD_ADDRESS",
        "password_attr": "ICLOUD_APP_PASSWORD",
        "host": "smtp.mail.me.com",
        "port": 587,
        "ssl": False,  # STARTTLS
        # iCloud は SMTP 送信分を控えに残さない。IMAP APPEND しないと
        # 本人の iPhone / Mail.app の「送信済み」に出てこない。
        "imap_host": "imap.mail.me.com",
        "sent_box": "Sent Messages",
    },
}


def _resolve_account(from_account: str):
    """送信アカウント名から (設定, 差出人アドレス, アプリパスワード) を返す。"""
    acct = SEND_ACCOUNTS.get(from_account)
    if not acct:
        raise ValueError(f"未知の送信アカウント: {from_account}（{'/'.join(SEND_ACCOUNTS)}）")
    sender = getattr(settings, acct["address_attr"], "")
    password = getattr(settings, acct["password_attr"], "")
    if not sender or not password:
        raise RuntimeError(
            f"{acct['address_attr']}/{acct['password_attr']} 未設定のためメール送信不可"
        )
    return acct, sender, password


def _deliver(acct: dict, sender: str, password: str, to: str, msg, timeout: int) -> None:
    """SMTP で1通送る。"""
    if acct["ssl"]:
        with smtplib.SMTP_SSL(acct["host"], acct["port"], timeout=timeout) as server:
            server.login(sender, password)
            server.sendmail(sender, [to], msg.as_string())
    else:
        with smtplib.SMTP(acct["host"], acct["port"], timeout=timeout) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, [to], msg.as_string())


def send_plain_email(
    to: str,
    subject: str,
    body: str,
    *,
    from_name: str = "Done",
    from_account: str = "gmail",
    reply_to: Optional[str] = None,
) -> None:
    """追跡なしの通知メールを1通送る（送信台帳に記録しない）。

    問い合わせフォームの内容をクライアント本人へ転送する等、こちらへの返信を
    期待しない一方向の連絡に使う。返信先を相手（問い合わせ主）にしたい場合は
    reply_to を渡す。
    """
    acct, sender, password = _resolve_account(from_account)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, sender))
    msg["To"] = to
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1] if "@" in sender else None)
    if reply_to:
        msg["Reply-To"] = reply_to

    _deliver(acct, sender, password, to, msg, 60)
    logger.info("plain email sent to=%s subject=%s", to, subject)


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
    attachments: Optional[Sequence[str]] = None,
    from_account: str = "gmail",
    in_reply_to: Optional[str] = None,
) -> dict:
    """メールを送信し、返信照合用に record_outbound する。

    from_account: "gmail"（既定）/ "gmail2" / "icloud"。相手が知っているアドレスから送る。

    Returns: {"sent": bool, "routing_key": str, "message_id": str, "route_id": str|None}
    Raises: 送信に失敗したら例外（呼び出し側で握る）。
    """
    acct, sender, password = _resolve_account(from_account)

    routing_key = _make_routing_key()
    message_id = make_msgid(domain=sender.split("@")[-1] if "@" in sender else None)

    # 本文末尾に控えめな照合フッタ（返信で引用されればヘッダ無しでも拾える）
    full_body = f"{body}\n\n--\n[Ref: {routing_key}]"

    paths = [Path(a) for a in (attachments or [])]
    for ap in paths:
        if not ap.is_file():
            raise FileNotFoundError(f"添付ファイルが見つかりません: {ap}")
    total = sum(ap.stat().st_size for ap in paths)
    if total > 20 * 1024 * 1024:
        raise ValueError(f"添付の合計が大きすぎます（{total / 1024 / 1024:.1f}MB）。20MB以内にしてください。")

    if paths:
        msg = MIMEMultipart()
        msg.attach(MIMEText(full_body, "plain", "utf-8"))
        for ap in paths:
            part = MIMEApplication(ap.read_bytes(), _subtype="octet-stream")
            part.add_header("Content-Disposition", "attachment", filename=ap.name)
            msg.attach(part)
    else:
        msg = MIMEText(full_body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, sender))
    msg["To"] = to
    msg["Message-ID"] = message_id
    msg["X-Dan-Ref"] = routing_key
    # 既存スレッドへの返信として送る場合（相手のメールの Message-ID を渡す）
    if in_reply_to:
        ref = in_reply_to.strip()
        if not ref.startswith("<"):
            ref = f"<{ref}>"
        msg["In-Reply-To"] = ref
        msg["References"] = ref

    # 添付が大きいと送信に時間がかかる（上り回線次第で数分）。20秒だと
    # 6MB 程度の添付で "Server not connected" になるため、添付量に応じて延ばす。
    smtp_timeout = 60 + int(total / (100 * 1024))  # 添付 1MB あたり +約10秒
    _deliver(acct, sender, password, to, msg, smtp_timeout)

    logger.info(
        "tracked email sent to=%s ref=%s msgid=%s attachments=%d",
        to, routing_key, message_id, len(paths),
    )

    # 送信済みフォルダへ控えを残す（サーバ側で自動保存しないアカウントのみ）。
    # 失敗しても送信自体は成功しているのでログだけ残す。
    if acct.get("imap_host"):
        try:
            import imaplib
            import time as _time

            raw = msg.as_bytes()
            with imaplib.IMAP4_SSL(acct["imap_host"], timeout=smtp_timeout) as imap:
                imap.login(sender, password)
                imap.append(
                    f'"{acct["sent_box"]}"',
                    r"\Seen",
                    imaplib.Time2Internaldate(_time.time()),
                    raw,
                )
        except Exception:
            logger.exception("append to sent box failed (mail was sent)")

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
        "attachments": [ap.name for ap in paths],
        "routing_key": routing_key,
        "message_id": message_id,
        "route_id": route_id,
    }
