"""
OTP Service - Phase 9: OTP Automation
メール・SMSからOTPを抽出・管理するサービス
"""
import re
import asyncio
import logging
import imaplib
import email as email_lib
import hashlib
import secrets
from email import utils as email_utils
from email.header import decode_header
from typing import Optional, List, Tuple
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.services.supabase_client import get_supabase_client
from app.models.otp_schemas import (
    OTPSource,
    OTPResult,
    OTP_PATTERNS,
    OTP_SENDER_DOMAINS,
    OTP_LINK_URL_PATTERN,
    OTP_LINK_TRUSTED_HOSTS,
    OTP_LINK_CONTEXT_KEYWORDS,
)

logger = logging.getLogger(__name__)


def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """
    ISO形式のdatetime文字列をパース（Supabaseの形式に対応）
    マイクロ秒の桁数が6桁でない場合も対応
    """
    if not dt_str:
        return None
    try:
        # Z を +00:00 に置換
        dt_str = dt_str.replace("Z", "+00:00")
        # fromisoformat を試す
        return datetime.fromisoformat(dt_str)
    except ValueError:
        # マイクロ秒の桁数問題に対応
        # 例: '2026-01-15T12:36:18.07883+00:00' → '2026-01-15T12:36:18.078830+00:00'
        try:
            # タイムゾーン部分を分離
            if '+' in dt_str:
                main_part, tz_part = dt_str.rsplit('+', 1)
                tz_part = '+' + tz_part
            elif dt_str.count('-') > 2:  # 負のタイムゾーン
                parts = dt_str.rsplit('-', 1)
                main_part = parts[0]
                tz_part = '-' + parts[1]
            else:
                main_part = dt_str
                tz_part = ''

            # マイクロ秒部分を6桁に調整
            if '.' in main_part:
                date_time, microsec = main_part.rsplit('.', 1)
                microsec = microsec.ljust(6, '0')[:6]  # 6桁に調整
                main_part = f"{date_time}.{microsec}"

            return datetime.fromisoformat(main_part + tz_part)
        except Exception:
            return datetime.now(timezone.utc)


def _raw_message_from_fetch(msg_data) -> Optional[bytes]:
    """IMAP fetch の応答から生メッセージを取り出す。

    応答の形はサーバによって違い、iCloud は本文を持たない要素を混ぜてくる。
    先頭要素を決め打ちすると取りこぼすので、bytes 本文を持つ最初のタプルを拾う。
    """
    for part in msg_data or []:
        if isinstance(part, tuple) and len(part) > 1 and isinstance(part[1], (bytes, bytearray)):
            return bytes(part[1])
    return None


def _message_datetime(email_message) -> Optional[datetime]:
    """メールの送信日時を tz-aware で返す。読めなければ None。"""
    raw = email_message.get("Date")
    if not raw:
        return None
    try:
        dt = email_utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# CSSやJSは本文扱いしない。色指定の #595959 が6桁コードとして拾われるため。
_HTML_NOISE_RE = re.compile(r'<(style|script|head)[^>]*>.*?</\1>', re.S | re.I)
_HTML_TAG_RE = re.compile(r'<[^>]+>')


def _message_text(email_message) -> str:
    """メールから本文テキストを取り出す。

    text/plain が無いメール（Epic の認証メールなど HTML のみ）でも
    コードやリンクを拾えるよう、無ければ HTML から起こす。
    """
    plain = ""
    html = ""
    parts = email_message.walk() if email_message.is_multipart() else [email_message]
    for part in parts:
        content_type = part.get_content_type()
        if content_type not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True) or b""
        text = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
        if content_type == "text/plain":
            plain += text
        else:
            html += text

    if plain.strip():
        return plain
    if not html:
        return ""
    return _HTML_TAG_RE.sub(" ", _HTML_NOISE_RE.sub(" ", html))


# メールプロバイダ別の IMAP ホスト（ドメイン → host）
_IMAP_HOSTS = {
    "gmail.com": "imap.gmail.com",
    "googlemail.com": "imap.gmail.com",
    "icloud.com": "imap.mail.me.com",
    "me.com": "imap.mail.me.com",
    "mac.com": "imap.mail.me.com",
    "outlook.com": "outlook.office365.com",
    "outlook.jp": "outlook.office365.com",
    "hotmail.com": "outlook.office365.com",
    "hotmail.co.jp": "outlook.office365.com",
    "live.com": "outlook.office365.com",
    "live.jp": "outlook.office365.com",
    "msn.com": "outlook.office365.com",
    "yahoo.co.jp": "imap.mail.yahoo.co.jp",
    "yahoo.com": "imap.mail.yahoo.com",
}
# プロバイダ別のアプリパスワード発行案内（ドメイン → 案内文）
_APP_PW_URLS = {
    "gmail.com": "https://myaccount.google.com/apppasswords （Googleで2段階認証ON必須）",
    "googlemail.com": "https://myaccount.google.com/apppasswords （Googleで2段階認証ON必須）",
    "icloud.com": "https://account.apple.com → サインインとセキュリティ → アプリ用パスワード（2ファクタ認証必須）",
    "me.com": "https://account.apple.com → アプリ用パスワード",
    "mac.com": "https://account.apple.com → アプリ用パスワード",
    "outlook.com": "https://account.microsoft.com/security → 追加のセキュリティ → アプリパスワード",
    "hotmail.com": "https://account.microsoft.com/security → アプリパスワード",
    "live.com": "https://account.microsoft.com/security → アプリパスワード",
    "yahoo.co.jp": "Yahoo! JAPAN ID設定 → ログインとセキュリティ → IMAP/SMTP用パスワード",
    "yahoo.com": "https://login.yahoo.com/myaccount/security → Generate app password",
}


def _email_domain(addr: Optional[str]) -> str:
    a = (addr or "").strip().lower()
    return a.split("@")[-1] if "@" in a else ""


def imap_host_for(addr: str, override: Optional[str] = None) -> str:
    """メールアドレスのドメインから IMAP ホストを決める。未知ドメインは imap.<domain> を試す。"""
    if override:
        return override
    d = _email_domain(addr)
    return _IMAP_HOSTS.get(d) or (f"imap.{d}" if d else "")


def app_password_guidance(addr: str) -> dict:
    """アドレスのプロバイダに応じたアプリパスワード発行案内と保存先サービス名を返す。"""
    d = _email_domain(addr)
    local = (addr or "").split("@")[0]
    url = _APP_PW_URLS.get(d)
    service = f"gmail_imap_{local}" if d in ("gmail.com", "googlemail.com") else f"imap_{local}"
    if url:
        note = f"{addr} のアプリパスワード発行: {url}"
    else:
        note = (
            f"{addr} のメールプロバイダで IMAP 用アプリパスワードを発行してください"
            f"（IMAPホストが imap.{d} でない場合は、そのホスト名も教えてください）"
        )
    return {"provider_domain": d, "url": url, "service": service, "note": note}


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
    
    def _extract_link_from_text(self, text: str) -> Optional[str]:
        """
        テキストからワンタイムURL（タップして再設定/認証するリンク）を抽出

        数字コードではなくリンクを送ってくるサービス（Instagramのパスワード
        再設定など）向け。宣伝リンクを誤って掴まないよう、信頼できる短縮
        ドメインか、本文に認証文脈のキーワードがある場合だけ採用する。

        Args:
            text: 解析対象のテキスト

        Returns:
            抽出されたURL、見つからない場合はNone
        """
        if not text:
            return None

        urls = re.findall(OTP_LINK_URL_PATTERN, text)
        if not urls:
            return None

        # "sign-in" と "sign in" を同一視するため区切り文字を空白に寄せる
        text_lower = re.sub(r'[-_]', ' ', text.lower())
        has_context = any(k.lower() in text_lower for k in OTP_LINK_CONTEXT_KEYWORDS)

        for url in urls:
            # SMSでは文末の句読点や括弧がURLに食い込むので落とす
            url = url.rstrip('.,;:!?)]｝』」）　')
            if not url:
                continue
            host = url.split("//", 1)[-1].split("/", 1)[0].split("?", 1)[0].lower()
            trusted = any(host == h or host.endswith("." + h) for h in OTP_LINK_TRUSTED_HOSTS)
            if trusted or has_context:
                logger.debug(f"OTP link extracted: host={host}")
                return url

        return None

    def _row_to_result(self, otp_data: dict, source: Optional[OTPSource] = None) -> OTPResult:
        """otp_extractions の1行を OTPResult に変換（code / link_url 両対応）"""
        return OTPResult(
            id=otp_data["id"],
            code=otp_data.get("otp_code"),
            link_url=otp_data.get("link_url"),
            source=source or OTPSource(otp_data["source"]),
            sender=otp_data.get("sender"),
            subject=otp_data.get("subject"),
            service=otp_data.get("service"),
            extracted_at=_parse_datetime(otp_data.get("extracted_at")) or datetime.now(timezone.utc),
            expires_at=_parse_datetime(otp_data.get("expires_at")),
            is_used=otp_data.get("is_used", False),
        )

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
                        extracted_at=_parse_datetime(otp_data.get("extracted_at")) or datetime.now(timezone.utc),
                        expires_at=_parse_datetime(otp_data.get("expires_at")),
                        is_used=otp_data.get("is_used", False),
                    )
        
        return None

    async def _find_imap_credential(
        self, user_id: str, email_address: str
    ) -> Optional[dict]:
        """指定メールアドレスのIMAP認証情報（アプリパスワード）を探す。

        命名規約 `gmail_imap_<localpart>` を優先し、無ければ imap 系サービスを
        走査して id がアドレスに一致するものを返す。第三者提供で各テナントが
        自分のアドレスのアプリパスワードを登録できるようにするための解決経路。
        """
        from app.services.credentials_service import get_credentials_service
        cs = get_credentials_service()
        addr = (email_address or "").strip().lower()
        if not addr:
            return None
        local = addr.split("@")[0]
        for svc in (f"gmail_imap_{local}", f"imap_{local}"):
            c = await cs.get_credential(user_id, svc)
            if c and (c.get("id") or "").lower() == addr:
                return c
        for s in await cs.list_credentials(user_id):
            name = s.get("service", "")
            if "imap" not in name.lower():
                continue
            c = await cs.get_credential(user_id, name)
            if c and (c.get("id") or "").lower() == addr:
                return c
        return None

    async def has_imap_access(self, user_id: str, email_address: str) -> bool:
        """指定アドレスのメールOTPをIMAPで読める認証情報があるか。"""
        return bool(await self._find_imap_credential(user_id, email_address))

    async def extract_otp_from_email_imap(
        self,
        user_id: str,
        service: Optional[str] = None,
        max_age_minutes: Optional[int] = None,
        subject_filter: Optional[str] = None,
        email_address: Optional[str] = None,
        want_link: bool = False,
    ) -> Optional[OTPResult]:
        """
        IMAPを使用してGmailからOTPを抽出（OAuth2不要）

        Args:
            user_id: ユーザーID
            service: 対象サービス（amazon, ex_reservation等）
            max_age_minutes: 最大経過時間（分）
            subject_filter: 件名フィルタ（直接届くメールOTPはNone=未読を走査）。
                            ※旧SMS Forwarder([SMSFW])経路はAPK転送に置換済みで廃止
            email_address: 読みたい受信箱のアドレス（指定時はそのアドレスの
                           アプリパスワードを使う。未指定は既定の gmail_imap）
            want_link: True の場合、数字コードではなくワンタイムURLを探す

        Returns:
            抽出されたOTP情報
        """
        from app.services.credentials_service import get_credentials_service

        if max_age_minutes is None:
            max_age_minutes = self.max_age_minutes

        # Gmail IMAP認証情報を取得（アドレス指定があればそのアドレスのものを探す）
        creds_service = get_credentials_service()
        if email_address:
            gmail_creds = await self._find_imap_credential(user_id, email_address)
        else:
            gmail_creds = await creds_service.get_credential(user_id, "gmail_imap")

        if not gmail_creds:
            logger.warning(f"No IMAP credentials for user {user_id} (address={email_address})")
            return None

        # 統一スキーマでは id がアドレス、password がアプリパスワード
        gmail_address = gmail_creds.get("id") or gmail_creds.get("email") or gmail_creds.get("username")
        gmail_password = gmail_creds.get("password") or gmail_creds.get("app_password")

        if not gmail_address or not gmail_password:
            logger.warning(f"Incomplete gmail_imap credentials for user {user_id}")
            return None

        try:
            # プロバイダに応じた IMAP ホストに接続（Gmail/iCloud/Outlook/Yahoo等）
            imap_host = gmail_creds.get("imap_host") or imap_host_for(gmail_address)
            logger.info(f"[IMAP] Connecting to {imap_host} for user {user_id[:8]}...")
            imap = imaplib.IMAP4_SSL(imap_host)
            imap.login(gmail_address, gmail_password)
            imap.select('INBOX')
            logger.info(f"[IMAP] Connected successfully")

            # 件名フィルタで検索
            if subject_filter:
                logger.debug(f"[IMAP] Searching for subject containing: {subject_filter}")
                _, messages = imap.search(None, 'SUBJECT', subject_filter)
            else:
                _, messages = imap.search(None, 'UNSEEN')

            message_ids = messages[0].split()
            logger.info(f"[IMAP] Found {len(message_ids)} emails matching filter")

            if not message_ids:
                logger.debug(f"[IMAP] No emails found with filter: {subject_filter}")
                imap.close()
                imap.logout()
                return None

            # 最新のメールから確認（最新10件）
            message_ids = list(reversed(message_ids[-10:]))
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)

            for msg_id in message_ids:
                # iCloud は (RFC822) に空応答を返して本文が一切取れないため
                # BODY.PEEK[] を使う。PEEK は既読フラグを立てないので、OTPを
                # 採用したメールだけ下で明示的に既読にする従来の挙動は保たれる。
                _, msg_data = imap.fetch(msg_id, '(BODY.PEEK[])')

                email_body = _raw_message_from_fetch(msg_data)
                if not email_body:
                    logger.debug(f"[IMAP] No body in fetch response for {msg_id}")
                    continue
                email_message = email_lib.message_from_bytes(email_body)

                # 認証待ちの時間内に届いたメールだけを見る。未読が大量にある
                # 受信箱では、広告メールの数字をOTPとして掴む事故が起きるため。
                sent_at = _message_datetime(email_message)
                if sent_at and sent_at < cutoff_time:
                    continue

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

                from_header = email_message.get('From', '')

                # 本文を取得
                body = _message_text(email_message)

                # OTP抽出
                logger.debug(f"[IMAP] Checking email - Subject: {subject[:50] if subject else 'None'}...")
                otp_code = None
                link_url = None
                if want_link:
                    link_url = self._extract_link_from_text(body) or self._extract_link_from_text(subject)
                else:
                    otp_code = self._extract_otp_from_text(subject) or self._extract_otp_from_text(body)

                if otp_code or link_url:
                    if otp_code:
                        logger.info(f"[IMAP] OTP extracted from email: {otp_code[:2]}****")
                    else:
                        host = link_url.split("//", 1)[-1].split("/", 1)[0]
                        logger.info(f"[IMAP] One-time link extracted from email: host={host}")
                    # メールを既読にする
                    imap.store(msg_id, '+FLAGS', '\\Seen')

                    imap.close()
                    imap.logout()

                    # OTPを保存
                    expires_at = datetime.now(timezone.utc) + timedelta(minutes=self.otp_expiry_minutes)
                    source_id = f"imap_{msg_id.decode() if isinstance(msg_id, bytes) else msg_id}"

                    # 重複チェック
                    existing = self.supabase.table("otp_extractions").select("id").eq(
                        "source_id", source_id
                    ).execute()

                    if existing.data:
                        return await self._get_otp_by_id(existing.data[0]["id"])

                    insert_data = {
                        "user_id": user_id,
                        "source": OTPSource.EMAIL.value,
                        "source_id": source_id,
                        "service": service,
                        "sender": from_header,
                        "subject": subject,
                        "otp_code": otp_code,
                        "link_url": link_url,
                        "expires_at": expires_at.isoformat(),
                    }

                    insert_result = self.supabase.table("otp_extractions").insert(insert_data).execute()

                    if insert_result.data:
                        return self._row_to_result(insert_result.data[0], OTPSource.EMAIL)

            imap.close()
            imap.logout()
            return None

        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP error: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to extract OTP via IMAP: {e}")
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

        # 最新のSMS OTPを検索（リンクのみの行は除く。コードを求める呼び出し向け）
        query = self.supabase.table("otp_extractions").select("*").eq(
            "user_id", user_id
        ).eq(
            "source", OTPSource.SMS.value
        ).eq(
            "is_used", False
        ).gte(
            "extracted_at", cutoff_time.isoformat()
        ).not_.is_(
            "otp_code", "null"
        ).order("extracted_at", desc=True).limit(1)

        if service:
            query = query.eq("service", service)

        result = query.execute()

        if result.data:
            return self._row_to_result(result.data[0], OTPSource.SMS)

        return None

    async def extract_link_from_sms(
        self,
        user_id: str,
        service: Optional[str] = None,
        max_age_minutes: Optional[int] = None,
    ) -> Optional[OTPResult]:
        """
        SMSからワンタイムURLを抽出（数字コードではなくリンクが届くサービス用）

        Args:
            user_id: ユーザーID
            service: 対象サービス
            max_age_minutes: 最大経過時間

        Returns:
            リンクを含むOTP情報
        """
        if max_age_minutes is None:
            max_age_minutes = self.max_age_minutes

        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)

        query = self.supabase.table("otp_extractions").select("*").eq(
            "user_id", user_id
        ).eq(
            "source", OTPSource.SMS.value
        ).eq(
            "is_used", False
        ).gte(
            "extracted_at", cutoff_time.isoformat()
        ).not_.is_(
            "link_url", "null"
        ).order("extracted_at", desc=True).limit(1)

        if service:
            query = query.eq("service", service)

        result = query.execute()

        if result.data:
            return self._row_to_result(result.data[0], OTPSource.SMS)

        return None

    async def extract_otp_from_voice(
        self,
        user_id: str,
        call_id: str,
        service: Optional[str] = None,
        max_age_minutes: Optional[int] = None,
    ) -> Optional[OTPResult]:
        """
        音声通話からOTPを抽出
        
        Args:
            user_id: ユーザーID
            call_id: 通話ID
            service: 対象サービス
            max_age_minutes: 最大経過時間
            
        Returns:
            抽出されたOTP情報
        """
        from app.services.voice_service import get_voice_service
        
        if max_age_minutes is None:
            max_age_minutes = self.max_age_minutes
        
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        
        # 1. 通話情報を取得
        voice_service = get_voice_service()
        call = await voice_service.get_call(call_id)
        
        if not call:
            logger.warning(f"Call not found: {call_id}")
            return None
        
        # 2. 通話の文字起こしを確認
        if not call.transcription:
            logger.warning(f"No transcription for call: {call_id}")
            return None
        
        # 3. 既存のOTPをチェック（重複防止）
        existing = self.supabase.table("otp_extractions").select("*").eq(
            "source_id", call_id
        ).execute()
        
        if existing.data:
            otp_data = existing.data[0]
            return OTPResult(
                id=otp_data["id"],
                code=otp_data["otp_code"],
                source=OTPSource.VOICE,
                sender=otp_data.get("sender"),
                service=otp_data.get("service"),
                extracted_at=_parse_datetime(otp_data.get("extracted_at")) or datetime.now(timezone.utc),
                expires_at=_parse_datetime(otp_data.get("expires_at")),
                is_used=otp_data.get("is_used", False),
            )
        
        # 4. 文字起こしからOTPを抽出
        otp_code = self._extract_otp_from_text(call.transcription)
        
        if not otp_code:
            logger.debug(f"No OTP found in transcription for call: {call_id}")
            return None
        
        # 5. 新規OTPを保存
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=self.otp_expiry_minutes)
        
        insert_data = {
            "user_id": user_id,
            "source": OTPSource.VOICE.value,
            "source_id": call_id,
            "service": service,
            "sender": call.from_number,
            "otp_code": otp_code,
            "expires_at": expires_at.isoformat(),
        }
        
        insert_result = self.supabase.table("otp_extractions").insert(insert_data).execute()
        
        if insert_result.data:
            otp_data = insert_result.data[0]
            logger.info(f"OTP extracted from voice for user {user_id}: {otp_code[:2]}****")
            return OTPResult(
                id=otp_data["id"],
                code=otp_data["otp_code"],
                source=OTPSource.VOICE,
                sender=otp_data.get("sender"),
                service=otp_data.get("service"),
                extracted_at=_parse_datetime(otp_data.get("extracted_at")) or datetime.now(timezone.utc),
                expires_at=_parse_datetime(otp_data.get("expires_at")),
                is_used=otp_data.get("is_used", False),
            )
        
        return None
    
    async def extract_otp_from_latest_voice_call(
        self,
        user_id: str,
        service: Optional[str] = None,
        max_age_minutes: Optional[int] = None,
    ) -> Optional[OTPResult]:
        """
        最新の音声通話からOTPを抽出
        
        Args:
            user_id: ユーザーID
            service: 対象サービス
            max_age_minutes: 最大経過時間
            
        Returns:
            抽出されたOTP情報
        """
        from app.services.voice_service import get_voice_service
        from app.models.voice_schemas import CallDirection
        
        if max_age_minutes is None:
            max_age_minutes = self.max_age_minutes
        
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        
        # 最新の着信を取得
        voice_service = get_voice_service()
        calls = await voice_service.get_call_history(
            user_id=user_id,
            direction=CallDirection.INBOUND,
            limit=5,
        )
        
        for call in calls:
            # 最大経過時間を超えた通話はスキップ
            if call.started_at and call.started_at < cutoff_time:
                continue
            
            # 文字起こしがあればOTP抽出を試行
            if call.transcription:
                result = await self.extract_otp_from_voice(
                    user_id=user_id,
                    call_id=call.id,
                    service=service,
                    max_age_minutes=max_age_minutes,
                )
                if result:
                    return result
        
        return None
    
    async def get_latest_otp(
        self,
        user_id: str,
        service: Optional[str] = None,
        source: Optional[str] = None,
        kind: str = "any",
    ) -> Optional[OTPResult]:
        """
        最新の未使用OTPを取得

        Args:
            user_id: ユーザーID
            service: 対象サービス（オプション）
            source: ソース（email/sms）
            kind: code=数字コードのみ / link=ワンタイムURLのみ / any=両方

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
        if kind == "code":
            query = query.not_.is_("otp_code", "null")
        elif kind == "link":
            query = query.not_.is_("link_url", "null")

        result = query.execute()

        if result.data:
            return self._row_to_result(result.data[0])

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
        
        extractions = [self._row_to_result(otp_data) for otp_data in result.data]

        return extractions, result.count or len(extractions)
    
    async def wait_for_otp(
        self,
        user_id: str,
        service: str,
        source: str = "email",
        timeout_seconds: Optional[int] = None,
        poll_interval: Optional[int] = None,
        email_address: Optional[str] = None,
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

        poll_count = 0
        while datetime.now(timezone.utc) < deadline:
            otp_result = None
            poll_count += 1

            # OTPを抽出
            if source == "email":
                if email_address:
                    # 指定アドレスの受信箱を IMAP で直接読む（直接届くメールOTP）
                    otp_result = await self.extract_otp_from_email_imap(
                        user_id=user_id,
                        service=service,
                        max_age_minutes=2,
                        subject_filter=None,
                        email_address=email_address,
                    )
                else:
                    # 既定: OAuth連携済み（オーナー）の Gmail から
                    otp_result = await self.extract_otp_from_email(
                        user_id=user_id,
                        service=service,
                        max_age_minutes=2,
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

    async def wait_for_link(
        self,
        user_id: str,
        service: Optional[str] = None,
        source: str = "sms",
        timeout_seconds: Optional[int] = None,
        poll_interval: Optional[int] = None,
        email_address: Optional[str] = None,
    ) -> Optional[str]:
        """
        ワンタイムURLが届くまで待機して取得

        数字コードではなく「タップして再設定」形式のリンクを送ってくる
        サービス（Instagramのパスワード再設定など）向け。

        Args:
            user_id: ユーザーID
            service: 対象サービス
            source: ソース（sms/email）
            timeout_seconds: タイムアウト秒数
            poll_interval: ポーリング間隔秒数
            email_address: source=email時に読む受信箱

        Returns:
            URL、タイムアウトの場合はNone
        """
        if timeout_seconds is None:
            timeout_seconds = self.wait_timeout
        if poll_interval is None:
            poll_interval = self.poll_interval

        logger.info(f"Waiting for one-time link (service={service}, source={source}, timeout={timeout_seconds}s)")

        deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)

        while datetime.now(timezone.utc) < deadline:
            if source == "email":
                result = await self.extract_otp_from_email_imap(
                    user_id=user_id,
                    service=service,
                    max_age_minutes=2,
                    subject_filter=None,
                    email_address=email_address,
                    want_link=True,
                )
            else:
                result = await self.extract_link_from_sms(
                    user_id=user_id,
                    service=service,
                    max_age_minutes=2,
                )

            if result and result.link_url and not result.is_used:
                await self.mark_otp_used(result.id)
                host = result.link_url.split("//", 1)[-1].split("/", 1)[0]
                logger.info(f"One-time link obtained for {service}: host={host}")
                return result.link_url

            await asyncio.sleep(poll_interval)

        logger.warning(f"Link wait timed out for {service}")
        return None


    async def save_sms_otp(
        self,
        from_number: str,
        body: str,
        message_sid: Optional[str] = None,
        user_id: Optional[str] = None,
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
        # OTPを抽出。数字コードが無くても、タップして認証するワンタイムURLが
        # 入っていれば取りこぼさずに保存する（Instagramのパスワード再設定など）
        otp_code = self._extract_otp_from_text(body)
        link_url = None if otp_code else self._extract_link_from_text(body)

        if not otp_code and not link_url:
            logger.debug(f"No OTP or link found in SMS from {from_number}")
            return None

        # 電話番号からユーザーを特定
        conn_result = None
        if not user_id:
            conn_result = self.supabase.table("sms_connections").select("user_id").eq(
                "is_active", True
            ).execute()
        
        if not user_id and not conn_result.data:
            logger.warning("No active SMS connection found")
            return None
        
        # 最初のアクティブなユーザーに紐付け（本番では電話番号でマッピング）
        if not user_id:
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
            "link_url": link_url,
            "expires_at": expires_at.isoformat(),
        }

        result = self.supabase.table("otp_extractions").insert(insert_data).execute()

        if result.data:
            otp_data = result.data[0]
            if otp_code:
                logger.info(f"SMS OTP saved: {otp_code[:2]}****")
            else:
                host = link_url.split("//", 1)[-1].split("/", 1)[0]
                logger.info(f"SMS one-time link saved: host={host}")
            return self._row_to_result(otp_data, OTPSource.SMS)

        return None
    
    async def register_apk_otp_device(
        self,
        user_id: str,
        device_name: Optional[str] = None,
    ) -> str:
        """Issue a revocable device token for direct APK SMS forwarding."""
        raw_token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        payload = {
            "user_id": user_id,
            "device_name": device_name,
            "token_hash": token_hash,
            "is_active": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        existing = self.supabase.table("apk_otp_devices").select("id").eq(
            "user_id", user_id
        ).execute()
        if existing.data:
            self.supabase.table("apk_otp_devices").update(payload).eq(
                "id", existing.data[0]["id"]
            ).execute()
        else:
            self.supabase.table("apk_otp_devices").insert(payload).execute()
        return raw_token

    async def disable_apk_otp_device(self, user_id: str) -> None:
        """Revoke SMS forwarding for a user's Android device."""
        self.supabase.table("apk_otp_devices").update({
            "is_active": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("user_id", user_id).execute()

    async def get_apk_otp_device_status(self, user_id: str) -> dict:
        result = self.supabase.table("apk_otp_devices").select(
            "device_name,is_active,last_received_at"
        ).eq("user_id", user_id).limit(1).execute()
        if not result.data:
            return {"enabled": False}
        device = result.data[0]
        return {
            "enabled": bool(device.get("is_active")),
            "device_name": device.get("device_name"),
            "last_received_at": device.get("last_received_at"),
        }

    async def save_apk_forwarded_sms(
        self,
        device_token: str,
        sender: str,
        body: str,
        message_id: Optional[str] = None,
    ) -> Optional[OTPResult]:
        """Authenticate an APK token and store an OTP without logging the SMS body."""
        token_hash = hashlib.sha256(device_token.encode("utf-8")).hexdigest()
        result = self.supabase.table("apk_otp_devices").select("id,user_id").eq(
            "token_hash", token_hash
        ).eq("is_active", True).limit(1).execute()
        if not result.data:
            raise ValueError("Invalid or revoked APK OTP device token")

        device = result.data[0]
        now = datetime.now(timezone.utc).isoformat()
        self.supabase.table("apk_otp_devices").update({
            "last_received_at": now,
            "updated_at": now,
        }).eq("id", device["id"]).execute()
        return await self.save_sms_otp(
            from_number=sender,
            body=body,
            message_sid=message_id,
            user_id=device["user_id"],
        )

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
            return self._row_to_result(result.data[0])
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


