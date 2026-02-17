"""
Gmail経由SMS OTP取得ヘルパー
SMS Forwarder → Gmail → OTP抽出
"""
import os
import re
import imaplib
import email
from datetime import datetime, timedelta
from email.header import decode_header
from typing import Optional
import logging
from dotenv import load_dotenv

# .envファイルを読み込み
load_dotenv()

logger = logging.getLogger(__name__)

GMAIL_ADDRESS = os.getenv('GMAIL_ADDRESS', '')
GMAIL_APP_PASSWORD = os.getenv('GMAIL_APP_PASSWORD', '')


def get_sms_otp_from_gmail(
    minutes: int = 5,
    subject_filter: str = "[SMSFW]",
    mark_as_read: bool = True
) -> Optional[str]:
    """
    Gmailから転送されたSMSを取得してOTPを抽出（同期版）

    Args:
        minutes: 何分前までのメールを確認するか
        subject_filter: 件名フィルター（SMS Forwarderは [SMSFW] を付ける）
        mark_as_read: OTP取得後にメールを既読にするか

    Returns:
        str: OTPコード、見つからなければNone
    """
    if not GMAIL_APP_PASSWORD:
        logger.error("GMAIL_APP_PASSWORD not set in environment")
        return None

    try:
        # Gmail IMAPに接続
        logger.debug("Connecting to Gmail IMAP...")
        imap = imaplib.IMAP4_SSL('imap.gmail.com')
        imap.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        imap.select('INBOX')

        # 件名に [SMSFW] を含むメールを検索
        _, messages = imap.search(None, 'SUBJECT', subject_filter)
        message_ids = messages[0].split()

        if not message_ids:
            logger.debug("No [SMSFW] emails found")
            imap.close()
            imap.logout()
            return None

        # 最新のメールから順に確認（最新10件）
        message_ids = list(reversed(message_ids[-10:]))

        for msg_id in message_ids:
            _, msg_data = imap.fetch(msg_id, '(RFC822)')
            email_body = msg_data[0][1]
            email_message = email.message_from_bytes(email_body)

            # 件名をデコード
            subject_raw = email_message.get('Subject', '')
            subject_decoded = decode_header(subject_raw)
            subject = ""
            for content, encoding in subject_decoded:
                if isinstance(content, bytes):
                    if encoding:
                        subject += content.decode(encoding, errors='ignore')
                    else:
                        subject += content.decode('utf-8', errors='ignore')
                else:
                    subject += str(content)

            # [SMSFW] が含まれていないメールはスキップ
            if subject_filter not in subject:
                continue

            # メール本文を取得
            body = ""
            if email_message.is_multipart():
                for part in email_message.walk():
                    if part.get_content_type() == "text/plain":
                        try:
                            body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        except Exception:
                            continue
                        break
            else:
                try:
                    body = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')
                except Exception:
                    continue

            # OTPパターンを探す（優先度順）
            otp_patterns = [
                # SmartEX専用パターン（最優先）
                r'ワンタイムパスワード[:：\s]*(\d{4,8})',
                # SafeKey
                r'(?:SafeKey|safekey|セーフキー)[:：\s]*(\d{4,8})',
                # 一般的なOTPパターン
                r'(?:認証コード|OTP|verification code|確認コード)[:：\s]*(\d{4,8})',
                # 汎用（6桁のみ、誤検知を減らす）
                r'(?<![\d.])\b(\d{6})\b(?![\d.])',  # 前後に数字がない6桁
            ]

            for pattern in otp_patterns:
                match = re.search(pattern, body, re.IGNORECASE)
                if match:
                    otp = match.group(1)
                    logger.info(f"OTP detected: {otp[:2]}****")

                    # この時点で既読にする
                    if mark_as_read:
                        imap.store(msg_id, '+FLAGS', '\\Seen')

                    imap.close()
                    imap.logout()
                    return otp

        imap.close()
        imap.logout()
        return None

    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP error: {e}")
        return None
    except Exception as e:
        logger.error(f"Error getting OTP from Gmail: {e}")
        return None


async def get_sms_otp_from_gmail_async(
    minutes: int = 5,
    subject_filter: str = "[SMSFW]",
    mark_as_read: bool = True
) -> Optional[str]:
    """
    Gmail OTP取得の非同期ラッパー

    Args:
        minutes: 何分前までのメールを確認するか
        subject_filter: 件名フィルター
        mark_as_read: OTP取得後にメールを既読にするか

    Returns:
        OTPコード、見つからなければNone
    """
    import asyncio

    # 同期関数をイベントループで実行
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        get_sms_otp_from_gmail,
        minutes,
        subject_filter,
        mark_as_read
    )
