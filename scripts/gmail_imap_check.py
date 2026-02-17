"""
Gmail IMAP経由でnoteの認証メールを取得し、認証URLを抽出する。
Googleアプリパスワードなしで動作するため、通常のパスワードでの接続を試みる。
失敗した場合はブラウザ経由でGmailを開く代替案を提示する。
"""
import imaplib
import email
from email.header import decode_header
import re
import sys


def check_note_verification_email(gmail_address: str, app_password: str) -> dict:
    """
    Gmail IMAPでnoteの認証メールを検索し、認証URLを返す。
    
    Returns:
        {"status": "found", "url": "https://...", "subject": "..."}
        {"status": "not_found", "message": "..."}
        {"status": "error", "message": "..."}
    """
    try:
        # IMAP接続
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(gmail_address, app_password)
        mail.select("INBOX")
        
        # noteからのメールを検索
        status, messages = mail.search(None, '(FROM "note.com")')
        if status != "OK" or not messages[0]:
            # noreplyも試す
            status, messages = mail.search(None, '(FROM "noreply")')
        
        if status != "OK" or not messages[0]:
            mail.logout()
            return {"status": "not_found", "message": "noteからのメールが見つかりませんでした"}
        
        # 最新のメールから確認
        email_ids = messages[0].split()
        for eid in reversed(email_ids[-10:]):  # 最新10件をチェック
            status, msg_data = mail.fetch(eid, "(RFC822)")
            if status != "OK":
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            
            # 件名をデコード
            subject = ""
            raw_subject = msg.get("Subject", "")
            decoded = decode_header(raw_subject)
            for part, charset in decoded:
                if isinstance(part, bytes):
                    subject += part.decode(charset or "utf-8", errors="replace")
                else:
                    subject += part
            
            # 本文からURLを抽出
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    ct = part.get_content_type()
                    if ct == "text/html":
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode("utf-8", errors="replace")
                            break
                    elif ct == "text/plain" and not body:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode("utf-8", errors="replace")
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="replace")
            
            # 認証URLを探す
            urls = re.findall(r'https://note\.com/[^\s<>"\']+(?:verify|confirm|activate|auth)[^\s<>"\']*', body)
            if not urls:
                # より広い範囲で探す
                urls = re.findall(r'https://note\.com/api/[^\s<>"\']+', body)
            if not urls:
                urls = re.findall(r'https://[^\s<>"\']*note[^\s<>"\']*(?:verify|confirm|activate|auth|token)[^\s<>"\']*', body)
            
            if urls:
                mail.logout()
                return {"status": "found", "url": urls[0], "subject": subject, "all_urls": urls}
        
        mail.logout()
        return {"status": "not_found", "message": "認証URLが含まれるメールが見つかりませんでした"}
        
    except imaplib.IMAP4.error as e:
        return {"status": "error", "message": f"IMAP認証エラー: {e}. Googleアプリパスワードが必要な可能性があります。"}
    except Exception as e:
        return {"status": "error", "message": f"エラー: {e}"}


if __name__ == "__main__":
    # コマンドライン引数からアプリパスワードを取得
    if len(sys.argv) < 2:
        print("Usage: python gmail_imap_check.py <app_password>")
        print("アプリパスワードの取得: https://myaccount.google.com/apppasswords")
        sys.exit(1)
    
    result = check_note_verification_email("0aw325171@gmail.com", sys.argv[1])
    print(f"\n結果: {result}")
