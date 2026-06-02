"""
Application Configuration - Phase 6 updated
"""
from pydantic_settings import BaseSettings
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """アプリケーション設定"""
    
    # Application
    APP_ENV: str = "development"
    APP_SECRET_KEY: str = "change-me-in-production"
    DAN_STREAMING_INPUT: bool = False
    
    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_ACCESS_TOKEN: str = ""  # Management API PAT for DDL migrations
    SUPABASE_PROJECT_REF: str = "omcnusihkpfyvzglttop"

    # fal.ai (video generation: Kling 3.0 Pro 経由)
    FAL_KEY: str = ""
    
    # Anthropic (Claude)
    ANTHROPIC_API_KEY: str = ""

    # MiniMax (M2.5 - main chat LLM)
    MINIMAX_API_KEY: str = ""

    # Secretary routing profile
    # - quality_first: delegate implementation-heavy work to business by default
    # - speed_first: keep more work in secretary unless planning uncertainty is high
    EXECUTION_PROFILE: str = "quality_first"

    # OpenAI (Embeddings for memory search)
    OPENAI_API_KEY: str = ""

    # Google Gemini (learning inference)
    GOOGLE_GEMINI_API_KEY: str = ""

    # Salonboard credentials encryption (Fernet base64, 32 bytes urlsafe)
    SALONBOARD_ENCRYPTION_KEY: str = ""
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Gmail API (Phase 5B)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GMAIL_REDIRECT_URI: str = "http://localhost:8000/api/v1/gmail/callback"
    GMAIL_POLL_INTERVAL_SECONDS: int = 300  # 5分

    # Gmail App Password (Phase 9: SMS OTP via Gmail / dan-notion IMAP fetch)
    GMAIL_APP_PASSWORD: str = ""
    GMAIL_ADDRESS: str = ""

    # iCloud Mail App-specific Password (dan-notion IMAP fetch)
    ICLOUD_ADDRESS: str = ""
    ICLOUD_APP_PASSWORD: str = ""
    
    # Attachment Storage (Phase 5C)
    ATTACHMENT_STORAGE_PATH: str = "./data/attachments"
    ATTACHMENT_MAX_SIZE_MB: int = 10
    
    # LINE Messaging API
    LINE_CHANNEL_ACCESS_TOKEN: str = ""
    LINE_CHANNEL_SECRET: str = ""
    
    # Encryption
    ENCRYPTION_KEY: str = ""
    
    # Tavily API (Smart Search)
    TAVILY_API_KEY: str = ""
    
    # Phase 6: Content Intelligence - OCR Settings
    OCR_PROVIDER: str = "tesseract"  # "tesseract" or "google_vision"
    TESSERACT_CMD: str = ""  # Path to tesseract executable (optional)
    
    # JWT Settings
    JWT_SECRET_KEY: str = ""  # Falls back to APP_SECRET_KEY if empty
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30  # 30 days
    
    # Cookie Settings (Frontend)
    COOKIE_DOMAIN: str = ""  # Empty for localhost
    COOKIE_SECURE: bool = False  # True in production (HTTPS)
    COOKIE_SAMESITE: str = "lax"  # "strict", "lax", or "none"
    
    # Phase 10: Voice Communication - Twilio
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""
    
    # Phase 10: Voice Communication - ElevenLabs
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = ""
    ELEVENLABS_MODEL_ID: str = "eleven_turbo_v2_5"
    
    # Phase 10: Voice Communication - General
    VOICE_MAX_CALL_DURATION_MINUTES: int = 30
    VOICE_DEFAULT_LANGUAGE: str = "ja"
    VOICE_WEBHOOK_BASE_URL: str = ""
    
    # EX Reservation (SmartEX) Credentials
    EX_MEMBER_ID: str = ""
    EX_PASSWORD: str = ""

    # Studio - fal.ai (Kling O3 video generation)
    FAL_API_KEY: str = ""

    # Captcha solving (2captcha) - reCAPTCHA等を人力中継で突破
    TWOCAPTCHA_API_KEY: str = ""

    # Web Push (VAPID)
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""

    # Deploy: external frontend/CORS
    ALLOWED_ORIGINS: str = ""  # comma-separated extra origins
    FRONTEND_URL: str = ""     # e.g. https://xxx.vercel.app
    
    # Properties for Gmail settings
    @property
    def gmail_client_id(self) -> str:
        return self.GOOGLE_CLIENT_ID
    
    @property
    def gmail_client_secret(self) -> str:
        return self.GOOGLE_CLIENT_SECRET
    
    @property
    def gmail_redirect_uri(self) -> str:
        return self.GMAIL_REDIRECT_URI
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """設定のシングルトンインスタンスを取得"""
    s = Settings()
    if s.APP_SECRET_KEY == "change-me-in-production":
        logger.warning(
            "APP_SECRET_KEY is using the default insecure value. "
            "Set a secure key in your .env file before deploying to production."
        )
    return s


settings = get_settings()

