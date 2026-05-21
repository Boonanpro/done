"""salonboard_credentials のデータスキーマ。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SalonboardCredentialsSet(BaseModel):
    """初回設定・更新リクエスト。
    パスワードを平文で受け取るため、HTTPSと取扱い注意必須。"""

    device_id: str = Field(..., min_length=8, max_length=128)
    stylist_name: str = Field(..., min_length=1, max_length=50)
    login_id: str = Field(..., min_length=1, max_length=200)
    password: str = Field(..., min_length=1, max_length=200)
    consent: bool = Field(..., description="秘密保持と取扱いへの同意")


class SalonboardCredentialsStatus(BaseModel):
    """設定状態の確認レスポンス。平文の login_id / password は決して含めない。"""

    has_credentials: bool
    stylist_name: Optional[str] = None
    last_used_at: Optional[datetime] = None
    consent_at: Optional[datetime] = None
