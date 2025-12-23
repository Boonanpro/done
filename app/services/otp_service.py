"""
OTP Service - Phase 9: OTP Automation
メール・SMSからOTPを抽出・管理するサービス
"""
import re
import asyncio
import logging
from typing import Optional, List, Tuple
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.services.supabase_client import get_supabase_client
from app.models.otp_schemas import (
    OTPSource,
    OTPResult,
    OTP_PATTERNS,
    OTP_SENDER_DOMAINS,
)

logger = logging.getLogger(__name__)

# デフォルト設定
DEFAULT_OTP_EXPIRY_MINUTES = 10
DEFAULT_MAX_AGE_MINUTES = 5
DEFAULT_POLL_INTERVAL_SECONDS = 5
DEFAULT_WAIT_TIMEOUT_SECONDS = 60


class OTPService:
    """OTP抽出・管理サービス"""
    
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.otp_expiry_minutes = getattr(settings, 'OTP_DEFAULT_EXPIRY_MINUTES', DEFAULT_OTP_EXPIRY_MINUTES)
        self.max_age_minutes = getattr(settings, 'OTP_MAX_AGE_MINUTES', DEFAULT_MAX_AGE_MINUTES)
        self.poll_interval = getattr(settings, 'OTP_POLL_INTERVAL_SECONDS', DEFAULT_POLL_INTERVAL_SECONDS)
        self.wait_timeout = getattr(settings, 'OTP_WAIT_TIMEOUT_SECONDS', DEFAULT_WAIT_TIMEOUT_SECONDS)
    
    def _extract_otp_from_text(self, text: str) -> Optional[str]:
        """
        テキストからOTPを抽出
        
        Args:
            text: 解析対象のテキスト
            
        Returns:
            抽出されたOTPコード、見つからない場合はNone
        """
        if not text:
            return None
        
        for pattern in OTP_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                otp = match.group(1)
                # 4〜8桁の数字であることを確認
                if otp.isdigit() and 4 <= len(otp) <= 8:
                    logger.debug(f"OTP extracted: {otp[:2]}****")
                    return otp
        
        return None
    
    def _match_service_domain(self, sender: str, service: Optional[str]) -> bool:
        """
        送信元がサービスのドメインと一致するか確認
        
        Args:
            sender: 送信元アドレス
            service: 対象サービス名
            
        Returns:
            一致する場合True
        """
        if not service or not sender:
            return True  # フィルタなしの場合は常にTrue
        
        domains = OTP_SENDER_DOMAINS.get(service.lower(), [])
        if not domains:
            return True  # ドメイン定義がない場合は許可
        
        sender_lower = sender.lower()
        return any(domain in sender_lower for domain in domains)
    
    async def extract_otp_from_email(
        self,
        user_id: str,
        service: Optional[str] = None,
        max_age_minutes: Optional[int] = None,
        sender_filter: Optional[str] = None,
    ) -> Optional[OTPResult]:
        """
        メールからOTPを抽出
        
        Args:
            user_id: ユーザーID
            service: 対象サービス（amazon, ex_reservation等）
            max_age_minutes: 最大経過時間（分）
            sender_filter: 送信元フィルタ
            
        Returns:
            抽出されたOTP情報
        """
        if max_age_minutes is None:
            max_age_minutes = self.max_age_minutes
        
        # 最新のメールを同期
        from app.services.gmail_service import get_gmail_service
        gmail_service = get_gmail_service()
        
        try:
            # メール同期
            await gmail_service.sync_emails(user_id, max_results=20)
        except Exception as e:
            logger.warning(f"Gmail sync failed: {e}")
        
        # 検知メッセージからOTPを検索
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        
        query = self.supabase.table("detected_messages").select("*").eq(
            "user_id", user_id
        ).eq(
            "source", "gmail"
        ).gte(
            "created_at", cutoff_time.isoformat()
        ).order("created_at", desc=True).limit(20)
        
        result = query.execute()
        
        for msg in result.data:
            sender = msg.get("sender_info", {}).get("from", "")
            subject = msg.get("subject", "")
            content = msg.get("content", "")
            
            # 送信元フィルタ
            if sender_filter and sender_filter.lower() not in sender.lower():
                continue
            
            # サービスドメインマッチング
            if not self._match_service_domain(sender, service):
                continue
            
            # OTP抽出（件名と本文から）
            otp_code = self._extract_otp_from_text(subject) or self._extract_otp_from_text(content)
            
            if otp_code:
                # 既存の同一OTPをチェック（重複防止）
                existing = self.supabase.table("otp_extractions").select("id").eq(
                    "source_id", msg["source_id"]
                ).execute()
                
                if existing.data:
                    # 既存のOTPを返す
                    return await self._get_otp_by_id(existing.data[0]["id"])
                
                # 新規OTPを保存
                expires_at = datetime.now(timezone.utc) + timedelta(minutes=self.otp_expiry_minutes)
                
                insert_data = {
                    "user_id": user_id,
                    "source": OTPSource.EMAIL.value,
                    "source_id": msg.get("source_id"),
                    "service": service,
                    "sender": sender,
                    "subject": subject,
                    "otp_code": otp_code,
                    "expires_at": expires_at.isoformat(),
                }
                
                insert_result = self.supabase.table("otp_extractions").insert(insert_data).execute()
                
                if insert_result.data:
                    otp_data = insert_result.data[0]
                    logger.info(f"OTP extracted from email for user {user_id}: {otp_code[:2]}****")
                    return OTPResult(
                        id=otp_data["id"],
                        code=otp_data["otp_code"],
                        source=OTPSource.EMAIL,
                        sender=otp_data.get("sender"),
                        subject=otp_data.get("subject"),
                        service=otp_data.get("service"),
                        extracted_at=datetime.fromisoformat(otp_data["extracted_at"].replace("Z", "+00:00")) if otp_data.get("extracted_at") else datetime.now(timezone.utc),
                        expires_at=datetime.fromisoformat(otp_data["expires_at"].replace("Z", "+00:00")) if otp_data.get("expires_at") else None,
                        is_used=otp_data.get("is_used", False),
                    )
        
        return None
    
    async def extract_otp_from_sms(
        self,
        user_id: str,
        service: Optional[str] = None,
        max_age_minutes: Optional[int] = None,
    ) -> Optional[OTPResult]:
        """
        SMSからOTPを抽出
        
        Args:
            user_id: ユーザーID
            service: 対象サービス
            max_age_minutes: 最大経過時間
            
        Returns:
            抽出されたOTP情報
        """
        if max_age_minutes is None:
            max_age_minutes = self.max_age_minutes
        
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        
        # 最新のSMS OTPを検索
        query = self.supabase.table("otp_extractions").select("*").eq(
            "user_id", user_id
        ).eq(
            "source", OTPSource.SMS.value
        ).eq(
            "is_used", False
        ).gte(
            "extracted_at", cutoff_time.isoformat()
        ).order("extracted_at", desc=True).limit(1)
        
        if service:
            query = query.eq("service", service)
        
        result = query.execute()
        
        if result.data:
            otp_data = result.data[0]
            return OTPResult(
                id=otp_data["id"],
                code=otp_data["otp_code"],
                source=OTPSource.SMS,
                sender=otp_data.get("sender"),
                service=otp_data.get("service"),
                extracted_at=datetime.fromisoformat(otp_data["extracted_at"].replace("Z", "+00:00")) if otp_data.get("extracted_at") else datetime.now(timezone.utc),
                expires_at=datetime.fromisoformat(otp_data["expires_at"].replace("Z", "+00:00")) if otp_data.get("expires_at") else None,
                is_used=otp_data.get("is_used", False),
            )
        
        return None
    
    async def get_latest_otp(
        self,
        user_id: str,
        service: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Optional[OTPResult]:
        """
        最新の未使用OTPを取得
        
        Args:
            user_id: ユーザーID
            service: 対象サービス（オプション）
            source: ソース（email/sms）
            
        Returns:
            最新のOTP情報
        """
        query = self.supabase.table("otp_extractions").select("*").eq(
            "user_id", user_id
        ).eq(
            "is_used", False
        ).gt(
            "expires_at", datetime.now(timezone.utc).isoformat()
        ).order("extracted_at", desc=True).limit(1)
        
        if service:
            query = query.eq("service", service)
        if source:
            query = query.eq("source", source)
        
        result = query.execute()
        
        if result.data:
            otp_data = result.data[0]
            return OTPResult(
                id=otp_data["id"],
                code=otp_data["otp_code"],
                source=OTPSource(otp_data["source"]),
                sender=otp_data.get("sender"),
                subject=otp_data.get("subject"),
                service=otp_data.get("service"),
                extracted_at=datetime.fromisoformat(otp_data["extracted_at"].replace("Z", "+00:00")) if otp_data.get("extracted_at") else datetime.now(timezone.utc),
                expires_at=datetime.fromisoformat(otp_data["expires_at"].replace("Z", "+00:00")) if otp_data.get("expires_at") else None,
                is_used=otp_data.get("is_used", False),
            )
        
        return None
    
    async def mark_otp_used(self, otp_id: str) -> bool:
        """
        OTPを使用済みにマーク
        
        Args:
            otp_id: OTP ID
            
        Returns:
            成功した場合True
        """
        result = self.supabase.table("otp_extractions").update({
            "is_used": True,
            "used_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", otp_id).execute()
        
        if result.data:
            logger.info(f"OTP marked as used: {otp_id}")
            return True
        return False
    
    async def get_otp_history(
        self,
        user_id: str,
        limit: int = 20,
        service: Optional[str] = None,
    ) -> Tuple[List[OTPResult], int]:
        """
        OTP抽出履歴を取得
        
        Args:
            user_id: ユーザーID
            limit: 取得件数
            service: サービスでフィルタ
            
        Returns:
            (OTPリスト, 総件数)
        """
        query = self.supabase.table("otp_extractions").select("*", count="exact").eq(
            "user_id", user_id
        ).order("extracted_at", desc=True).limit(limit)
        
        if service:
            query = query.eq("service", service)
        
        result = query.execute()
        
        extractions = []
        for otp_data in result.data:
            extractions.append(OTPResult(
                id=otp_data["id"],
                code=otp_data["otp_code"],
                source=OTPSource(otp_data["source"]),
                sender=otp_data.get("sender"),
                subject=otp_data.get("subject"),
                service=otp_data.get("service"),
                extracted_at=datetime.fromisoformat(otp_data["extracted_at"].replace("Z", "+00:00")) if otp_data.get("extracted_at") else datetime.now(timezone.utc),
                expires_at=datetime.fromisoformat(otp_data["expires_at"].replace("Z", "+00:00")) if otp_data.get("expires_at") else None,
                is_used=otp_data.get("is_used", False),
            ))
        
        return extractions, result.count or len(extractions)
    
    async def wait_for_otp(
        self,
        user_id: str,
        service: str,
        source: str = "email",
        timeout_seconds: Optional[int] = None,
        poll_interval: Optional[int] = None,
    ) -> Optional[str]:
        """
        OTPが届くまで待機して取得（Executor向け）
        
        Args:
            user_id: ユーザーID
            service: 対象サービス
            source: ソース（email/sms）
            timeout_seconds: タイムアウト秒数
            poll_interval: ポーリング間隔秒数
            
        Returns:
            OTPコード、タイムアウトの場合はNone
        """
        if timeout_seconds is None:
            timeout_seconds = self.wait_timeout
        if poll_interval is None:
            poll_interval = self.poll_interval
        
        logger.info(f"Waiting for OTP (service={service}, source={source}, timeout={timeout_seconds}s)")
        
        start_time = datetime.now(timezone.utc)
        deadline = start_time + timedelta(seconds=timeout_seconds)
        
        while datetime.now(timezone.utc) < deadline:
            # OTPを抽出
            if source == "email":
                otp_result = await self.extract_otp_from_email(
                    user_id=user_id,
                    service=service,
                    max_age_minutes=2,  # 短い時間で最新を取得
                )
            else:
                otp_result = await self.extract_otp_from_sms(
                    user_id=user_id,
                    service=service,
                    max_age_minutes=2,
                )
            
            if otp_result and not otp_result.is_used:
                # OTPを使用済みにマーク
                await self.mark_otp_used(otp_result.id)
                logger.info(f"OTP obtained for {service}: {otp_result.code[:2]}****")
                return otp_result.code
            
            # 待機
            await asyncio.sleep(poll_interval)
        
        logger.warning(f"OTP wait timed out for {service}")
        return None
    
    async def save_sms_otp(
        self,
        from_number: str,
        body: str,
        message_sid: Optional[str] = None,
    ) -> Optional[OTPResult]:
        """
        SMS Webhookから受信したOTPを保存
        
        Args:
            from_number: 送信元電話番号
            body: SMSメッセージ本文
            message_sid: TwilioメッセージSID
            
        Returns:
            保存されたOTP情報
        """
        # OTPを抽出
        otp_code = self._extract_otp_from_text(body)
        
        if not otp_code:
            logger.debug(f"No OTP found in SMS from {from_number}")
            return None
        
        # 電話番号からユーザーを特定
        conn_result = self.supabase.table("sms_connections").select("user_id").eq(
            "is_active", True
        ).execute()
        
        if not conn_result.data:
            logger.warning("No active SMS connection found")
            return None
        
        # 最初のアクティブなユーザーに紐付け（本番では電話番号でマッピング）
        user_id = conn_result.data[0]["user_id"]
        
        # サービスを推測（送信元番号ベース）
        service = self._guess_service_from_sms(from_number, body)
        
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=self.otp_expiry_minutes)
        
        insert_data = {
            "user_id": user_id,
            "source": OTPSource.SMS.value,
            "source_id": message_sid,
            "service": service,
            "sender": from_number,
            "otp_code": otp_code,
            "expires_at": expires_at.isoformat(),
        }
        
        result = self.supabase.table("otp_extractions").insert(insert_data).execute()
        
        if result.data:
            otp_data = result.data[0]
            logger.info(f"SMS OTP saved: {otp_code[:2]}****")
            return OTPResult(
                id=otp_data["id"],
                code=otp_data["otp_code"],
                source=OTPSource.SMS,
                sender=otp_data.get("sender"),
                service=otp_data.get("service"),
                extracted_at=datetime.fromisoformat(otp_data["extracted_at"].replace("Z", "+00:00")) if otp_data.get("extracted_at") else datetime.now(timezone.utc),
                expires_at=datetime.fromisoformat(otp_data["expires_at"].replace("Z", "+00:00")) if otp_data.get("expires_at") else None,
                is_used=False,
            )
        
        return None
    
    def _guess_service_from_sms(self, from_number: str, body: str) -> Optional[str]:
        """SMSの内容からサービスを推測"""
        body_lower = body.lower()
        
        service_keywords = {
            "amazon": ["amazon", "アマゾン"],
            "rakuten": ["楽天", "rakuten"],
            "ex_reservation": ["ex予約", "smartex", "新幹線", "jr"],
            "google": ["google", "グーグル"],
            "line": ["line", "ライン"],
            "yahoo": ["yahoo", "ヤフー"],
        }
        
        for service, keywords in service_keywords.items():
            for keyword in keywords:
                if keyword.lower() in body_lower:
                    return service
        
        return None
    
    async def _get_otp_by_id(self, otp_id: str) -> Optional[OTPResult]:
        """IDでOTPを取得"""
        result = self.supabase.table("otp_extractions").select("*").eq("id", otp_id).execute()
        
        if result.data:
            otp_data = result.data[0]
            return OTPResult(
                id=otp_data["id"],
                code=otp_data["otp_code"],
                source=OTPSource(otp_data["source"]),
                sender=otp_data.get("sender"),
                subject=otp_data.get("subject"),
                service=otp_data.get("service"),
                extracted_at=datetime.fromisoformat(otp_data["extracted_at"].replace("Z", "+00:00")) if otp_data.get("extracted_at") else datetime.now(timezone.utc),
                expires_at=datetime.fromisoformat(otp_data["expires_at"].replace("Z", "+00:00")) if otp_data.get("expires_at") else None,
                is_used=otp_data.get("is_used", False),
            )
        return None
    
    async def get_sms_status(self, user_id: str) -> dict:
        """
        SMS受信設定状態を取得
        
        Args:
            user_id: ユーザーID
            
        Returns:
            設定状態
        """
        # Twilio設定の確認
        twilio_configured = bool(
            getattr(settings, 'TWILIO_ACCOUNT_SID', None) and
            getattr(settings, 'TWILIO_AUTH_TOKEN', None) and
            getattr(settings, 'TWILIO_PHONE_NUMBER', None)
        )
        
        # ユーザーのSMS接続を確認
        result = self.supabase.table("sms_connections").select("*").eq(
            "user_id", user_id
        ).execute()
        
        if result.data:
            conn = result.data[0]
            return {
                "configured": twilio_configured,
                "phone_number": getattr(settings, 'TWILIO_PHONE_NUMBER', None),
                "webhook_url": f"{getattr(settings, 'APP_URL', 'http://localhost:8000')}/api/v1/otp/sms/webhook",
                "is_active": conn.get("is_active", False),
            }
        
        return {
            "configured": twilio_configured,
            "phone_number": getattr(settings, 'TWILIO_PHONE_NUMBER', None) if twilio_configured else None,
            "webhook_url": f"{getattr(settings, 'APP_URL', 'http://localhost:8000')}/api/v1/otp/sms/webhook" if twilio_configured else None,
            "is_active": False,
        }


# シングルトンインスタンス
_otp_service: Optional[OTPService] = None


def get_otp_service() -> OTPService:
    """OTPサービスのインスタンスを取得"""
    global _otp_service
    if _otp_service is None:
        _otp_service = OTPService()
    return _otp_service

