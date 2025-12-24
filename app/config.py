"""
Application Configuration - Phase 6 updated
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """アプリケーション設定"""
    
    # Application
    APP_ENV: str = "development"
    APP_SECRET_KEY: str = "change-me-in-production"
    
    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    
    # Anthropic (Claude)
    ANTHROPIC_API_KEY: str = ""
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Gmail API (Phase 5B)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GMAIL_REDIRECT_URI: str = "http://localhost:8000/api/v1/gmail/callback"
    GMAIL_POLL_INTERVAL_SECONDS: int = 300  # 5分
    
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
    return Settings()


settings = get_settings()

