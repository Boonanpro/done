"""問い合わせ・ウェイティングリスト登録のメール通知。

Gmail の SMTP(アプリパスワード)で、フォーム送信内容を運用担当のメールへ届ける。
保存処理を止めないため、呼び出し側は失敗を握りつぶす(ベストエフォート)。
"""
import logging
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# scope ごとの通知先。未登録の scope は DEFAULT_RECIPIENT に届く。
SCOPE_RECIPIENTS = {
    "paina-contact": "shub6923@gmail.com",
    "paina-waitlist": "shub6923@gmail.com",
}
DEFAULT_RECIPIENT = "shub6923@gmail.com"

SCOPE_LABELS = {
    "paina-contact": "お問い合わせ",
    "paina-waitlist": "Done ウェイティングリスト登録",
}


def _send_smtp(
    to_addr: str,
    subject: str,
    body: str,
    *,
    from_name: str = "株式会社パイナ お問い合わせ",
    reply_to: Optional[str] = None,
    headers: Optional[dict] = None,
) -> None:
    sender = settings.GMAIL_ADDRESS
    password = settings.GMAIL_APP_PASSWORD
    if not sender or not password:
        logger.warning("GMAIL_ADDRESS/APP_PASSWORD 未設定のため問い合わせ通知メールを送信できません")
        return

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, sender))
    msg["To"] = to_addr
    if reply_to:
        msg["Reply-To"] = reply_to
    # スレッド返信用 (In-Reply-To / References 等)
    for k, v in (headers or {}).items():
        if v:
            msg[k] = v

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as server:
        server.login(sender, password)
        server.sendmail(sender, [to_addr], msg.as_string())


def send_inquiry_notification(
    scope: str,
    name: str,
    message: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    company: Optional[str] = None,
    source_url: Optional[str] = None,
) -> None:
    """同期送信。呼び出し側で asyncio.to_thread でラップして使う。"""
    try:
        to_addr = SCOPE_RECIPIENTS.get(scope, DEFAULT_RECIPIENT)
        label = SCOPE_LABELS.get(scope, scope)
        subject = f"【パイナHP】{label}: {name} 様"

        lines = [
            f"株式会社パイナ のサイトから{label}が届きました。",
            "",
            f"お名前: {name}",
        ]
        if company:
            lines.append(f"会社名: {company}")
        if email:
            lines.append(f"メール: {email}")
        if phone:
            lines.append(f"電話: {phone}")
        lines.append("")
        lines.append("内容:")
        lines.append(message or "(なし)")
        if source_url:
            lines.append("")
            lines.append(f"送信元ページ: {source_url}")
        body = "\n".join(lines)

        _send_smtp(to_addr, subject, body)
        logger.info("inquiry notification sent scope=%s to=%s", scope, to_addr)
    except Exception as e:  # noqa: BLE001 - 通知失敗は保存を妨げない
        logger.warning("inquiry notification failed scope=%s: %s", scope, e)


# 登録・送信した本人へ送る自動確認メール（控え）。営業メールではなく受付確認のみ。
OWNER_REPLY_TO = "shub6923@gmail.com"
PAINA_SITE_URL = "https://paina.info"


def _autoreply_content(scope: str, name: str) -> Optional[tuple[str, str]]:
    # name がプレースホルダ（未記入）の場合は宛名を省く。
    has_name = bool(name) and name not in ("（お名前未記入）", "(お名前未記入)")
    greeting = f"{name} 様\n\n" if has_name else ""

    if scope == "paina-waitlist":
        subject = "【株式会社パイナ】Done（ダン）ウェイティングリストのご登録ありがとうございます"
        body = (
            f"{greeting}"
            "このたびは、AIエージェント「Done（ダン）」のウェイティングリストに"
            "ご登録いただきありがとうございます。\n\n"
            "ご登録を受け付けました。提供開始が決まりましたら、"
            "このメールアドレス宛に最初にご案内いたします。\n"
            "営業メールをお送りすることはありません。\n\n"
            "──────────\n"
            "株式会社パイナ\n"
            f"{PAINA_SITE_URL}\n\n"
            "※本メールは送信専用アドレスから自動送信しています。\n"
            f"　ご返信は {OWNER_REPLY_TO} で承ります。"
        )
        return subject, body

    if scope == "paina-contact":
        subject = "【株式会社パイナ】お問い合わせを受け付けました"
        body = (
            f"{greeting}"
            "お問い合わせいただきありがとうございます。\n\n"
            "以下の内容で受け付けました。担当より折り返しご連絡いたします。\n"
            "今しばらくお待ちください。\n\n"
            "──────────\n"
            "株式会社パイナ\n"
            f"{PAINA_SITE_URL}\n\n"
            "※本メールは送信専用アドレスから自動送信しています。\n"
            f"　ご返信は {OWNER_REPLY_TO} で承ります。"
        )
        return subject, body

    return None


def send_inquiry_autoreply(scope: str, name: str, email: Optional[str]) -> None:
    """登録・送信した本人へ受付確認メールを送る（ベストエフォート）。"""
    if not email:
        return
    try:
        content = _autoreply_content(scope, name)
        if not content:
            return
        subject, body = content
        _send_smtp(
            email,
            subject,
            body,
            from_name="株式会社パイナ",
            reply_to=OWNER_REPLY_TO,
        )
        logger.info("inquiry autoreply sent scope=%s to=%s", scope, email)
    except Exception as e:  # noqa: BLE001 - 確認メール失敗は保存を妨げない
        logger.warning("inquiry autoreply failed scope=%s: %s", scope, e)
