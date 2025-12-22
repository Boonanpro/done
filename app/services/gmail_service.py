"""
Gmail Service - Phase 5B: メール受信検知
Gmail API連携によるメール検知・取得
"""
import os
import base64
import json
import logging
from typing import Optional, List, Tuple
from datetime import datetime
from email.utils import parsedate_to_datetime

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import settings
from app.services.supabase_client import get_supabase_client
from app.services.encryption import encrypt_data, decrypt_data
from app.services.message_detection import get_detection_service
from app.models.detection_schemas import MessageSource

logger = logging.getLogger(__name__)

# Gmail API スコープ
GMAIL_SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.labels',
]


class GmailService:
    """Gmail連携サービス"""
    
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.client_config = self._get_client_config()
    
    def _get_client_config(self) -> dict:
        """OAuth2クライアント設定を取得"""
        return {
            "web": {
                "client_id": settings.gmail_client_id,
                "client_secret": settings.gmail_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.gmail_redirect_uri],
            }
        }
    
    def get_auth_url(self, user_id: str) -> str:
        """OAuth2認証URLを生成"""
        flow = Flow.from_client_config(
            self.client_config,
            scopes=GMAIL_SCOPES,
            redirect_uri=settings.gmail_redirect_uri,
        )
        
        auth_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent',
            state=user_id,  # stateにuser_idを含める
        )
        
        return auth_url
    
    async def handle_callback(self, code: str, user_id: str) -> Tuple[bool, str, Optional[str]]:
        """
        OAuth2コールバックを処理
        
        Returns:
            (success, message, email)
        """
        try:
            flow = Flow.from_client_config(
                self.client_config,
                scopes=GMAIL_SCOPES,
                redirect_uri=settings.gmail_redirect_uri,
            )
            
            flow.fetch_token(code=code)
            credentials = flow.credentials
            
            # Gmailアドレスを取得
            service = build('gmail', 'v1', credentials=credentials)
            profile = service.users().getProfile(userId='me').execute()
            email = profile.get('emailAddress', '')
            
            # トークンを暗号化して保存
            token_data = {
                'token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'token_uri': credentials.token_uri,
                'client_id': credentials.client_id,
                'client_secret': credentials.client_secret,
                'scopes': list(credentials.scopes) if credentials.scopes else GMAIL_SCOPES,
            }
            
            encrypted_token = encrypt_data(json.dumps(token_data))
            
            # 既存のレコードを確認
            existing = self.supabase.table("gmail_connections").select("id").eq("user_id", user_id).execute()
            
            if existing.data:
                # 更新
                self.supabase.table("gmail_connections").update({
                    "email": email,
                    "encrypted_token": encrypted_token,
                    "is_active": True,
                    "last_history_id": None,  # 履歴IDをリセット
                }).eq("user_id", user_id).execute()
            else:
                # 新規作成
                self.supabase.table("gmail_connections").insert({
                    "user_id": user_id,
                    "email": email,
                    "encrypted_token": encrypted_token,
                    "is_active": True,
                }).execute()
            
            logger.info(f"Gmail connected for user {user_id}: {email}")
            return True, "Gmail access authorized successfully", email
            
        except Exception as e:
            logger.error(f"Gmail OAuth callback failed: {e}")
            return False, str(e), None
    
    async def get_connection_status(self, user_id: str) -> dict:
        """Gmail連携状態を取得"""
        result = self.supabase.table("gmail_connections").select("*").eq("user_id", user_id).execute()
        
        if not result.data:
            return {
                "connected": False,
                "email": None,
                "last_sync": None,
                "is_active": False,
            }
        
        conn = result.data[0]
        return {
            "connected": True,
            "email": conn["email"],
            "last_sync": conn.get("last_sync_at"),
            "is_active": conn.get("is_active", False),
        }
    
    async def disconnect(self, user_id: str) -> bool:
        """Gmail連携を解除"""
        result = self.supabase.table("gmail_connections").update({
            "is_active": False,
        }).eq("user_id", user_id).execute()
        
        return bool(result.data)
    
    def _get_credentials(self, encrypted_token: str) -> Optional[Credentials]:
        """暗号化されたトークンから認証情報を復元"""
        try:
            token_data = json.loads(decrypt_data(encrypted_token))
            
            credentials = Credentials(
                token=token_data['token'],
                refresh_token=token_data.get('refresh_token'),
                token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
                client_id=token_data.get('client_id', settings.gmail_client_id),
                client_secret=token_data.get('client_secret', settings.gmail_client_secret),
                scopes=token_data.get('scopes', GMAIL_SCOPES),
            )
            
            # トークンが期限切れの場合はリフレッシュ
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            
            return credentials
        except Exception as e:
            logger.error(f"Failed to get credentials: {e}")
            return None
    
    async def sync_emails(self, user_id: str, max_results: int = 50) -> Tuple[int, List[str]]:
        """
        新着メールを同期
        
        Returns:
            (new_message_count, message_ids)
        """
        # 接続情報を取得
        conn_result = self.supabase.table("gmail_connections").select("*").eq("user_id", user_id).eq("is_active", True).execute()
        
        if not conn_result.data:
            raise ValueError("Gmail not connected")
        
        conn = conn_result.data[0]
        credentials = self._get_credentials(conn["encrypted_token"])
        
        if not credentials:
            raise ValueError("Invalid Gmail credentials")
        
        try:
            service = build('gmail', 'v1', credentials=credentials)
            
            # 新着メール取得クエリ
            query = "is:unread"
            if conn.get("last_history_id"):
                # 差分取得（履歴IDがある場合）
                # Note: history.listは複雑なので、シンプルにunreadメールを取得
                pass
            
            # メール一覧取得
            results = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results,
            ).execute()
            
            messages = results.get('messages', [])
            new_message_ids = []
            detection_service = get_detection_service()
            
            for msg_info in messages:
                msg_id = msg_info['id']
                
                # 既に検知済みかチェック
                existing = self.supabase.table("detected_messages").select("id").eq(
                    "source", MessageSource.GMAIL.value
                ).eq("source_id", msg_id).execute()
                
                if existing.data:
                    continue
                
                # メール詳細を取得
                message = service.users().messages().get(
                    userId='me',
                    id=msg_id,
                    format='full',
                ).execute()
                
                # ヘッダーを解析
                headers = {h['name'].lower(): h['value'] for h in message.get('payload', {}).get('headers', [])}
                subject = headers.get('subject', '(No Subject)')
                from_addr = headers.get('from', '')
                date_str = headers.get('date', '')
                
                # 本文を取得
                body = self._extract_body(message.get('payload', {}))
                
                # 添付ファイル情報を取得
                attachments = self._extract_attachment_info(message.get('payload', {}), msg_id)
                
                # 検知メッセージとして保存
                await detection_service.detect_message(
                    user_id=user_id,
                    source=MessageSource.GMAIL,
                    content=body,
                    source_id=msg_id,
                    subject=subject,
                    sender_info={
                        "from": from_addr,
                        "date": date_str,
                    },
                    metadata={
                        "thread_id": message.get('threadId'),
                        "label_ids": message.get('labelIds', []),
                        "attachments": attachments,
                        "snippet": message.get('snippet', ''),
                    },
                )
                
                new_message_ids.append(msg_id)
            
            # 最終同期時刻を更新
            self.supabase.table("gmail_connections").update({
                "last_sync_at": datetime.utcnow().isoformat(),
            }).eq("user_id", user_id).execute()
            
            logger.info(f"Gmail sync completed for user {user_id}: {len(new_message_ids)} new messages")
            return len(new_message_ids), new_message_ids
            
        except HttpError as e:
            logger.error(f"Gmail API error: {e}")
            raise ValueError(f"Gmail API error: {e}")
    
    def _extract_body(self, payload: dict) -> str:
        """メール本文を抽出"""
        body = ""
        
        if 'parts' in payload:
            for part in payload['parts']:
                if part.get('mimeType') == 'text/plain':
                    data = part.get('body', {}).get('data', '')
                    if data:
                        body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                        break
                elif part.get('mimeType') == 'text/html' and not body:
                    data = part.get('body', {}).get('data', '')
                    if data:
                        # HTMLの場合はタグを除去（簡易的）
                        import re
                        html = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                        body = re.sub(r'<[^>]+>', '', html)
                elif 'parts' in part:
                    # ネストされたパート（multipart）
                    body = self._extract_body(part)
                    if body:
                        break
        else:
            data = payload.get('body', {}).get('data', '')
            if data:
                body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
        
        return body.strip()
    
    def _extract_attachment_info(self, payload: dict, message_id: str) -> List[dict]:
        """添付ファイル情報を抽出"""
        attachments = []
        
        def process_parts(parts):
            for part in parts:
                filename = part.get('filename', '')
                if filename and part.get('body', {}).get('attachmentId'):
                    attachments.append({
                        "filename": filename,
                        "mime_type": part.get('mimeType', 'application/octet-stream'),
                        "size": part.get('body', {}).get('size', 0),
                        "attachment_id": part['body']['attachmentId'],
                        "message_id": message_id,
                    })
                if 'parts' in part:
                    process_parts(part['parts'])
        
        if 'parts' in payload:
            process_parts(payload['parts'])
        
        return attachments
    
    async def get_attachment(
        self,
        user_id: str,
        message_id: str,
        attachment_id: str,
    ) -> Tuple[bytes, str, str]:
        """
        添付ファイルをダウンロード
        
        Returns:
            (data, filename, mime_type)
        """
        # 接続情報を取得
        conn_result = self.supabase.table("gmail_connections").select("*").eq("user_id", user_id).eq("is_active", True).execute()
        
        if not conn_result.data:
            raise ValueError("Gmail not connected")
        
        conn = conn_result.data[0]
        credentials = self._get_credentials(conn["encrypted_token"])
        
        if not credentials:
            raise ValueError("Invalid Gmail credentials")
        
        service = build('gmail', 'v1', credentials=credentials)
        
        # 添付ファイルをダウンロード
        attachment = service.users().messages().attachments().get(
            userId='me',
            messageId=message_id,
            id=attachment_id,
        ).execute()
        
        data = base64.urlsafe_b64decode(attachment['data'])
        
        # メッセージからファイル名とMIMEタイプを取得
        message = service.users().messages().get(
            userId='me',
            id=message_id,
            format='metadata',
            metadataHeaders=['Content-Type'],
        ).execute()
        
        filename = "attachment"
        mime_type = "application/octet-stream"
        
        def find_attachment(parts):
            nonlocal filename, mime_type
            for part in parts:
                if part.get('body', {}).get('attachmentId') == attachment_id:
                    filename = part.get('filename', 'attachment')
                    mime_type = part.get('mimeType', 'application/octet-stream')
                    return True
                if 'parts' in part:
                    if find_attachment(part['parts']):
                        return True
            return False
        
        payload = message.get('payload', {})
        if 'parts' in payload:
            find_attachment(payload['parts'])
        
        return data, filename, mime_type


# シングルトンインスタンス
_gmail_service: Optional[GmailService] = None


def get_gmail_service() -> GmailService:
    """Gmailサービスのインスタンスを取得"""
    global _gmail_service
    if _gmail_service is None:
        _gmail_service = GmailService()
    return _gmail_service


