"""
特定のメールIDの内容を読む
"""
import os
import imaplib
import email
from email.header import decode_header
from dotenv import load_dotenv

load_dotenv()

GMAIL_ADDRESS = "0aw325171@gmail.com"
GMAIL_APP_PASSWORD = os.getenv('GMAIL_APP_PASSWORD')


def read_email(email_id, output_file=None):
    """メールIDを指定して内容を取得"""
    imap = imaplib.IMAP4_SSL('imap.gmail.com')
    imap.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    imap.select('INBOX')

    _, msg_data = imap.fetch(email_id.encode(), '(RFC822)')
    email_body = msg_data[0][1]
    email_message = email.message_from_bytes(email_body)

    # 出力先
    import sys
    if output_file:
        out = open(output_file, 'w', encoding='utf-8')
    else:
        out = sys.stdout

    # 件名
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

    out.write(f"Subject: {subject}\n")
    out.write("\n")
    out.write(f"From: {email_message.get('From', '')}\n")
    out.write(f"Date: {email_message.get('Date', '')}\n")
    out.write("\n")

    # 本文（全てのパート）
    out.write("Message parts:\n")
    if email_message.is_multipart():
        for i, part in enumerate(email_message.walk()):
            content_type = part.get_content_type()
            out.write(f"  Part {i}: {content_type}\n")

            if "text" in content_type:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode('utf-8', errors='ignore')
                        out.write(f"\nBody (Part {i}):\n")
                        out.write(body)
                        out.write("\n\n")
                except Exception as e:
                    out.write(f"    Error decoding: {e}\n")
    else:
        try:
            payload = email_message.get_payload(decode=True)
            if payload:
                body = payload.decode('utf-8', errors='ignore')
                out.write("Body (single part):\n")
                out.write(body)
            else:
                out.write("Body (raw):\n")
                out.write(str(email_message.get_payload()))
            out.write("\n\n")
        except Exception as e:
            out.write(f"Error: {e}\n")

    imap.close()
    imap.logout()

    if output_file:
        out.close()


if __name__ == "__main__":
    import sys
    email_id = sys.argv[1] if len(sys.argv) > 1 else "23412"
    output_file = f"email_{email_id}.txt"
    read_email(email_id, output_file)
    print(f"Email content saved to {output_file}")

    # ファイルの内容を表示
    with open(output_file, 'r', encoding='utf-8') as f:
        print(f.read())
