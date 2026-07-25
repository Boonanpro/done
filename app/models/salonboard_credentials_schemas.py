"""salonboard_credentials のデータスキーマ。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SalonboardCredentialsSet(BaseModel):
    """初回設定・更新リクエスト。
    パスワードを平文で受け取るため、HTTPSと取扱い注意必須。"""

    device_id: str = Field(..., min_length=8, max_length=128)
    stylist_name: str = Field(..., min_length=1, max_length=50)
    email: str = Field(..., min_length=3, max_length=200, description="連絡用メールアドレス")
    login_id: str = Field(..., min_length=1, max_length=200)
    password: str = Field(..., min_length=1, max_length=200)
    consent: bool = Field(..., description="秘密保持と取扱いへの同意")

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        v = v.strip()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("メールアドレスの形式が正しくありません")
        return v


class SalonboardCredentialsStatus(BaseModel):
    """設定状態の確認レスポンス。平文の login_id / password は決して含めない。"""

    has_credentials: bool
    stylist_name: Optional[str] = None
    last_used_at: Optional[datetime] = None
    consent_at: Optional[datetime] = None
    # サーバー発行の長期クッキーから本人を復元できた場合、採用すべき device_id を返す。
    # 端末側(localStorage)の記憶が iOS の自動削除等で消えても、これで無入力復帰できる。
    device_id: Optional[str] = None
