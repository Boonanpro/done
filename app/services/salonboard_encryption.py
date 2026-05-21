"""
Fernet 対称鍵暗号化サービス（サロンボード認証情報用）。

サロンボードのログイン ID/パスワードを保存する際の暗号化と、
自動投稿時にのみ行う復号を担う。

設計方針:
- 暗号化鍵は環境変数 SALONBOARD_ENCRYPTION_KEY（Fernet 形式の base64）
- 平文を返す API は提供しない。復号はサーバー内部の自動投稿処理だけが呼ぶ
- 鍵を将来ローテーションできるよう encryption_version カラムを併用
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class EncryptionError(Exception):
    """暗号化/復号の失敗を表す例外。"""


class SalonboardEncryptionService:
    def __init__(self, key: str | None = None):
        actual_key = key or settings.SALONBOARD_ENCRYPTION_KEY
        if not actual_key:
            raise EncryptionError(
                "SALONBOARD_ENCRYPTION_KEY が未設定です。`Fernet.generate_key()` で生成して .env に追加してください。"
            )
        if isinstance(actual_key, str):
            actual_key = actual_key.encode("utf-8")
        try:
            self._fernet = Fernet(actual_key)
        except Exception as e:  # noqa: BLE001
            raise EncryptionError(f"SALONBOARD_ENCRYPTION_KEY が不正な形式です: {e}")

    def encrypt(self, plaintext: str) -> str:
        if plaintext is None or plaintext == "":
            raise ValueError("plaintext が空です")
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as e:
            raise EncryptionError(f"復号に失敗しました: {e}")


_service: SalonboardEncryptionService | None = None


def get_salonboard_encryption_service() -> SalonboardEncryptionService:
    """シングルトンの暗号化サービスを返す。"""
    global _service
    if _service is None:
        _service = SalonboardEncryptionService()
    return _service
