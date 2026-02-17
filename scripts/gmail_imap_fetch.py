"""
Gmail IMAP経由でnoteの認証メールを取得し、認証URLを抽出する。
"""
import imaplib
import email
from email.header import decode_header
import re
import sys
import traceback


def fetch_note_verification(gmail_address: str, password: str) -> None:
    """Gmail IMAPでnoteの認証メールを検索し、認証URLを表示する。"""
    print(f"[1] IMAP接続中... (imap.gmail.com:993)")
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        print("[2] ログイン中...")
        mail.login(gmail_address, password)
        print("[3] ログイン成功!")
    except imaplib.IMAP4.error as e:
        print(f"[ERROR] IMAP認証エラー: {e}")
        print("  → Googleアカウントで2段階認証が有効な場合、アプリパスワードが必要です")
        print("  → https://myaccount.google.com/apppasswords で生成してください")
        return
    except Exception as e:
        print(f"[ERROR] 接続エラー: {e}")
        traceback.print_exc()
        return

    try:
        mail.select("INBOX")
        
        # noteからのメールを検索（複数パターン）
        search_queries = [
            '(FROM "note.com")',
            '(FROM "noreply@note.com")',
            '(FROM "note")',
            '(SUBJECT "認証")',
            '(SUBJECT "verify")',
            '(SUBJECT "確認")',
        ]
        
        all_email_ids = set()
        for query in search_queries:
            try:
                status, messages = mail.search(None, query)
                if status == "OK" and messages[0]:
                    for eid in messages[0].split():
                        all_email_ids.add(eid)
            except:
                pass
        
        if not all_email_ids:
            # 全メール取得して最新10件をチェック
            print("[4] 特定検索でヒットなし。全メールの最新10件を確認...")
            status, messages = mail.search(None, "ALL")
            if status == "OK" and messages[0]:
                all_ids = messages[0].split()
                all_email_ids = set(all_ids[-10:])
                print(f"  → 全メール数: {len(all_ids)}")
            else:
                print("[ERROR] メールが1通もありません")
                mail.logout()
                return
        
        print(f"[4] {len(all_email_ids)}件のメールを確認中...")
        
        verification_urls = []
        
        for eid in sorted(all_email_ids, reverse=True):
            status, msg_data = mail.fetch(eid, "(RFC822)")
            if status != "OK":
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            
            # 送信元
            from_addr = msg.get("From", "")
            
            # 件名をデコード
            subject = ""
            raw_subject = msg.get("Subject", "")
            decoded = decode_header(raw_subject)
            for part, charset in decoded:
                if isinstance(part, bytes):
                    subject += part.decode(charset or "utf-8", errors="replace")
                else:
                    subject += part
            
            # 日付
            date = msg.get("Date", "")
            
            print(f"\n  --- メール ---")
            print(f"  From: {from_addr}")
            print(f"  Subject: {subject}")
            print(f"  Date: {date}")
            
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
            
            # noteの認証URLパターンを検索
            patterns = [
                r'https://note\.com/[^\s<>"\']+(?:verify|confirm|activate|auth|token)[^\s<>"\']*',
                r'https://note\.com/api/[^\s<>"\']+',
                r'https://[^\s<>"\']*note\.com[^\s<>"\']*(?:verify|confirm|activate|auth|token)[^\s<>"\']*',
                r'href="(https://note\.com/[^\s"\']+)"',
            ]
            
            found_urls = []
            for pattern in patterns:
                urls = re.findall(pattern, body)
                found_urls.extend(urls)
            
            if found_urls:
                print(f"  ★ 認証URL発見!")
                for url in found_urls:
                    print(f"    → {url}")
                    verification_urls.extend(found_urls)
        
        if verification_urls:
            print(f"\n[5] 認証URL一覧:")
            for url in set(verification_urls):
                print(f"  → {url}")
        else:
            print(f"\n[5] 認証URLは見つかりませんでした")
            print("  → noteからメールが届いていない可能性があります")
            print("  → noteで認証メールの再送信を試してください")
        
        mail.logout()
        print("\n[完了] IMAP接続を閉じました")
        
    except Exception as e:
        print(f"[ERROR] メール取得エラー: {e}")
        traceback.print_exc()
        try:
            mail.logout()
        except:
            pass


if __name__ == "__main__":
    gmail_address = "0aw325171@gmail.com"
    password = sys.argv[1] if len(sys.argv) > 1 else "Emoto589"
    fetch_note_verification(gmail_address, password)
