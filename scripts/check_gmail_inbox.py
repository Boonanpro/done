"""
Gmailの受信トレイを確認してSMS Forwarderからのメール形式を調査
"""
import os
import imaplib
import email
from datetime import datetime
from email.header import decode_header
from dotenv import load_dotenv

load_dotenv()

GMAIL_ADDRESS = "0aw325171@gmail.com"
GMAIL_APP_PASSWORD = os.getenv('GMAIL_APP_PASSWORD')

def decode_str(s):
    """メールヘッダーのデコード"""
    if s is None:
        return ""

    if isinstance(s, bytes):
        s = s.decode('utf-8', errors='ignore')

    decoded = decode_header(s)
    result = []
    for content, encoding in decoded:
        if isinstance(content, bytes):
            if encoding:
                result.append(content.decode(encoding, errors='ignore'))
            else:
                result.append(content.decode('utf-8', errors='ignore'))
        else:
            result.append(str(content))
    return ''.join(result)

def check_inbox():
    """受信トレイの最新メールを確認"""

    if not GMAIL_APP_PASSWORD:
        print("[ERROR] GMAIL_APP_PASSWORD not set in .env")
        return

    try:
        # Gmail IMAPに接続
        print("Connecting to Gmail...")
        imap = imaplib.IMAP4_SSL('imap.gmail.com')
        imap.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        imap.select('INBOX')
        print("[OK] Connected")
        print()

        # 最新10件のメールを取得
        _, messages = imap.search(None, 'ALL')
        message_ids = messages[0].split()

        if not message_ids:
            print("No emails found")
            imap.close()
            imap.logout()
            return

        # 最新10件を逆順で
        message_ids = list(reversed(message_ids[-10:]))

        print("=" * 70)
        print(f"Latest {len(message_ids)} emails in inbox:")
        print("=" * 70)
        print()

        for i, msg_id in enumerate(message_ids, 1):
            _, msg_data = imap.fetch(msg_id, '(RFC822)')
            email_body = msg_data[0][1]
            email_message = email.message_from_bytes(email_body)

            # ヘッダー情報
            from_header = decode_str(email_message.get('From', ''))
            subject = decode_str(email_message.get('Subject', ''))
            date_header = email_message.get('Date', '')

            print(f"[{i}] Email ID: {msg_id.decode()}")
            print(f"    From: {from_header}")
            print(f"    Subject: {subject}")
            print(f"    Date: {date_header}")

            # メール本文の一部を取得
            body = ""
            if email_message.is_multipart():
                for part in email_message.walk():
                    if part.get_content_type() == "text/plain":
                        try:
                            body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        except:
                            body = str(part.get_payload())
                        break
            else:
                try:
                    body = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')
                except:
                    body = str(email_message.get_payload())

            # 本文プレビュー（最初の200文字）
            body_preview = body.replace('\n', ' ').replace('\r', ' ').strip()[:200]
            print(f"    Body: {body_preview}...")
            print()

        imap.close()
        imap.logout()

        print("=" * 70)
        print("Looking for SMS Forwarder emails")
        print("=" * 70)
        print()
        print("Check the 'From' field above to identify SMS Forwarder emails")
        print("Common patterns:")
        print("  - SMS Forwarder")
        print("  - Your phone number")
        print("  - Android device name")
        print("  - The Gmail address itself (if forwarding as yourself)")

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_inbox()
