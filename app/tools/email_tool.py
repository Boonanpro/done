"""
Email Tools using Gmail API
"""
from typing import Optional
from langchain_core.tools import tool
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import base64
import os
import pickle

from app.config import settings

# Gmail APIのスコープ
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]


def get_gmail_service():
    """Gmail APIサービスを取得"""
    creds = None
    token_path = os.path.join(os.path.expanduser("~"), ".ai_secretary", "gmail_token.pickle")
    credentials_path = os.path.join(os.path.expanduser("~"), ".ai_secretary", "gmail_credentials.json")
    
    # 保存されたトークンがあれば読み込み
    if os.path.exists(token_path):
        with open(token_path, "rb") as token:
            creds = pickle.load(token)
    
    # トークンがないか期限切れの場合
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(
                    f"Gmail認証情報ファイルが見つかりません: {credentials_path}\n"
                    "Google Cloud Consoleから認証情報をダウンロードして配置してください。"
                )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # トークンを保存
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, "wb") as token:
            pickle.dump(creds, token)
    
    return build("gmail", "v1", credentials=creds)


@tool
async def send_email(
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
) -> str:
    """
    メールを送信します。
    
    Args:
        to: 宛先メールアドレス
        subject: 件名
        body: 本文
        cc: CC（任意）
        
    Returns:
        送信結果のメッセージ
    """
    try:
        service = get_gmail_service()
        
        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = subject
        if cc:
            message["cc"] = cc
        
        message.attach(MIMEText(body, "plain", "utf-8"))
        
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        
        result = service.users().messages().send(
            userId="me",
            body={"raw": raw}
        ).execute()
        
        return f"メールを送信しました。ID: {result['id']}"
    except FileNotFoundError as e:
        return f"エラー: {str(e)}"
    except Exception as e:
        return f"エラー: メール送信に失敗しました - {str(e)}"


@tool
async def search_email(
    query: str,
    max_results: int = 10,
) -> str:
    """
    メールを検索します。
    
    Args:
        query: 検索クエリ（Gmailの検索構文を使用可能）
        max_results: 最大取得件数
        
    Returns:
        検索結果のメール一覧
    """
    try:
        service = get_gmail_service()
        
        results = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results,
        ).execute()
        
        messages = results.get("messages", [])
        
        if not messages:
            return "該当するメールが見つかりませんでした。"
        
        email_list = []
        for msg in messages:
            msg_data = service.users().messages().get(
                userId="me",
                id=msg["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            
            headers = {h["name"]: h["value"] for h in msg_data["payload"]["headers"]}
            email_list.append(
                f"- ID: {msg['id']}\n"
                f"  From: {headers.get('From', 'N/A')}\n"
                f"  Subject: {headers.get('Subject', 'N/A')}\n"
                f"  Date: {headers.get('Date', 'N/A')}"
            )
        
        return f"検索結果 ({len(messages)}件):\n\n" + "\n\n".join(email_list)
    except FileNotFoundError as e:
        return f"エラー: {str(e)}"
    except Exception as e:
        return f"エラー: メール検索に失敗しました - {str(e)}"


@tool
async def read_email(message_id: str) -> str:
    """
    指定されたIDのメールの内容を読み取ります。
    
    Args:
        message_id: メールのID
        
    Returns:
        メールの内容
    """
    try:
        service = get_gmail_service()
        
        msg = service.users().messages().get(
            userId="me",
            id=message_id,
            format="full",
        ).execute()
        
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        
        # 本文を取得
        body = ""
        if "parts" in msg["payload"]:
            for part in msg["payload"]["parts"]:
                if part["mimeType"] == "text/plain":
                    body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                    break
        elif "body" in msg["payload"] and "data" in msg["payload"]["body"]:
            body = base64.urlsafe_b64decode(msg["payload"]["body"]["data"]).decode("utf-8")
        
        return (
            f"From: {headers.get('From', 'N/A')}\n"
            f"To: {headers.get('To', 'N/A')}\n"
            f"Subject: {headers.get('Subject', 'N/A')}\n"
            f"Date: {headers.get('Date', 'N/A')}\n"
            f"\n本文:\n{body}"
        )
    except FileNotFoundError as e:
        return f"エラー: {str(e)}"
    except Exception as e:
        return f"エラー: メール読み取りに失敗しました - {str(e)}"

