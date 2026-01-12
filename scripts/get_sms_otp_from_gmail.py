"""
Gmail経由で転送されたSMSからOTPコードを抽出
SMS Forwarder → Gmail → このスクリプト
"""
import os
import re
import imaplib
import email
from datetime import datetime, timedelta
from email.header import decode_header
from dotenv import load_dotenv

load_dotenv()

GMAIL_ADDRESS = "0aw325171@gmail.com"
GMAIL_APP_PASSWORD = os.getenv('GMAIL_APP_PASSWORD')  # .envに追加が必要

def get_latest_sms_otp(minutes=5, subject_filter="[SMSFW]"):
    """
    Gmailから転送されたSMSを取得してOTPを抽出

    Args:
        minutes: 何分前までのメールを確認するか
        subject_filter: 件名フィルター（SMS Forwarderは [SMSFW] を付ける）

    Returns:
        str: OTPコード、見つからなければNone
    """
    print("=" * 70)
    print("Checking SMS forwarded to Gmail...")
    print("=" * 70)
    print()
    print(f"Gmail: {GMAIL_ADDRESS}")
    print(f"Looking for emails with subject: {subject_filter}")
    print(f"Time range: Last {minutes} minutes")
    print()

    if not GMAIL_APP_PASSWORD:
        print("[ERROR] GMAIL_APP_PASSWORD not set in .env")
        print()
        print("To set up Gmail App Password:")
        print("1. Go to https://myaccount.google.com/apppasswords")
        print("2. Create new app password")
        print("3. Add to .env: GMAIL_APP_PASSWORD=your_16_char_password")
        return None

    try:
        # Gmail IMAPに接続
        print("Connecting to Gmail IMAP...")
        imap = imaplib.IMAP4_SSL('imap.gmail.com')
        imap.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        imap.select('INBOX')
        print("  [OK] Connected")
        print()

        # 件名に [SMSFW] を含むメールを検索
        print("Searching for [SMSFW] emails...")

        # IMAPのSUBJECT検索を使用
        _, messages = imap.search(None, 'SUBJECT', '[SMSFW]')

        message_ids = messages[0].split()

        if not message_ids:
            print("No [SMSFW] emails found in inbox")
            print()
            print("Troubleshooting:")
            print("  - Make sure SMS Forwarder is forwarding to this Gmail")
            print("  - Check SMS Forwarder subject prefix is [SMSFW]")
            imap.close()
            imap.logout()
            return None

        # 最新のメールから順に確認（最新10件）
        message_ids = list(reversed(message_ids[-10:]))

        print(f"Found {len(message_ids)} [SMSFW] email(s), checking...")
        print()

        cutoff_time = datetime.now() - timedelta(minutes=minutes)

        for msg_id in message_ids:
            _, msg_data = imap.fetch(msg_id, '(RFC822)')

            email_body = msg_data[0][1]
            email_message = email.message_from_bytes(email_body)

            # 送信者を確認
            from_header = email_message.get('From', '')

            # 件名をデコード
            subject_raw = email_message.get('Subject', '')
            from email.header import decode_header
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

            date_header = email_message.get('Date', '')

            # [SMSFW] が含まれていないメールはスキップ
            if subject_filter not in subject:
                continue

            print(f"Email from: {from_header}")
            print(f"  Subject: {subject}")
            print(f"  Date: {date_header}")

            # メール本文を取得
            body = ""
            if email_message.is_multipart():
                for part in email_message.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        break
            else:
                body = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')

            print(f"  Body preview: {body[:200]}...")
            print()

            # OTPパターンを探す（優先度順）
            otp_patterns = [
                # SmartEX専用パターン（最優先）
                r'ワンタイムパスワード[:：\s]*(\d{4,8})',
                # 一般的なOTPパターン
                r'(?:認証コード|OTP|verification code|確認コード)[:：\s]*(\d{4,8})',
                # SafeKeyなど
                r'(?:SafeKey|safekey|セーフキー)[:：\s]*(\d{4,8})',
                # 汎用（6桁のみ、誤検知を減らす）
                r'(?<![\d.])\b(\d{6})\b(?![\d.])',  # 前後に数字がない6桁
            ]

            for pattern in otp_patterns:
                match = re.search(pattern, body, re.IGNORECASE)
                if match:
                    otp = match.group(1)
                    print(f"  -> OTP detected: {otp}")
                    print()

                    # この時点で未読を既読にする
                    imap.store(msg_id, '+FLAGS', '\\Seen')

                    imap.close()
                    imap.logout()

                    print("=" * 70)
                    print(f"OTP Code: {otp}")
                    print("=" * 70)
                    return otp

            print("  -> No OTP found in this email")
            print()

        imap.close()
        imap.logout()

        print("No OTP found in recent emails")
        return None

    except imaplib.IMAP4.error as e:
        print(f"[ERROR] IMAP error: {e}")
        print()
        print("Common issues:")
        print("  - Invalid app password")
        print("  - 2-factor authentication not enabled on Gmail")
        print("  - IMAP not enabled in Gmail settings")
        return None
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    import sys

    # コマンドライン引数で時間範囲を指定可能
    minutes = int(sys.argv[1]) if len(sys.argv) > 1 else 10

    print()
    otp = get_latest_sms_otp(minutes=minutes)

    if otp:
        print()
        print("SUCCESS: OTP retrieved from Gmail")
    else:
        print()
        print("FAILED: Could not retrieve OTP")
        print()
        print("Troubleshooting:")
        print("  1. Check that SMS Forwarder is running on Android")
        print("  2. Verify email is being forwarded to 0aw325171@gmail.com")
        print("  3. Check GMAIL_APP_PASSWORD in .env")
        print("  4. Make sure OTP SMS was sent in the last 10 minutes")
