"""
Encryption Service for Secure Credential Storage
"""
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import os
import json
from typing import Any

from app.config import settings


class EncryptionService:
    """認証情報の暗号化・復号化サービス"""
    
    def __init__(self, key: str = None):
        """
        Args:
            key: 暗号化キー（32バイトの文字列）。
                 指定しない場合は環境変数から取得。
        """
        if key is None:
            key = settings.ENCRYPTION_KEY
        
        if not key:
            # 開発用にランダムキーを生成（本番では必ず固定キーを使用）
            key = Fernet.generate_key().decode()
        
        self._fernet = self._create_fernet(key)
    
    def _create_fernet(self, key: str) -> Fernet:
        """Fernetインスタンスを作成"""
        # キーが32バイトでない場合はPBKDF2で派生
        if len(key) != 44:  # Fernet keyは44文字のbase64
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"ai_secretary_salt",  # 本番では環境変数から取得
                iterations=100000,
            )
            derived_key = base64.urlsafe_b64encode(
                kdf.derive(key.encode())
            )
            return Fernet(derived_key)
        return Fernet(key.encode())
    
    def encrypt(self, data: str) -> bytes:
        """
        文字列を暗号化
        
        Args:
            data: 暗号化する文字列
            
        Returns:
            暗号化されたバイト列
        """
        return self._fernet.encrypt(data.encode())
    
    def decrypt(self, encrypted_data: bytes) -> str:
        """
        暗号化されたデータを復号
        
        Args:
            encrypted_data: 暗号化されたバイト列
            
        Returns:
            復号された文字列
        """
        return self._fernet.decrypt(encrypted_data).decode()
    
    def encrypt_dict(self, data: dict[str, Any]) -> bytes:
        """
        辞書を暗号化
        
        Args:
            data: 暗号化する辞書
            
        Returns:
            暗号化されたバイト列
        """
        json_str = json.dumps(data, ensure_ascii=False)
        return self.encrypt(json_str)
    
    def decrypt_dict(self, encrypted_data: bytes) -> dict[str, Any]:
        """
        暗号化された辞書を復号
        
        Args:
            encrypted_data: 暗号化されたバイト列
            
        Returns:
            復号された辞書
        """
        json_str = self.decrypt(encrypted_data)
        return json.loads(json_str)
    
    def encrypt_credential(
        self,
        username: str,
        password: str,
        extra: dict[str, Any] = None,
    ) -> bytes:
        """
        認証情報を暗号化
        
        Args:
            username: ユーザー名
            password: パスワード
            extra: その他の認証情報
            
        Returns:
            暗号化された認証情報
        """
        credential = {
            "username": username,
            "password": password,
        }
        if extra:
            credential.update(extra)
        
        return self.encrypt_dict(credential)
    
    def decrypt_credential(self, encrypted_data: bytes) -> dict[str, Any]:
        """
        暗号化された認証情報を復号
        
        Args:
            encrypted_data: 暗号化された認証情報
            
        Returns:
            復号された認証情報（username, password, その他）
        """
        return self.decrypt_dict(encrypted_data)


# シングルトンインスタンス
_encryption_service: EncryptionService = None


def get_encryption_service() -> EncryptionService:
    """暗号化サービスのシングルトンインスタンスを取得"""
    global _encryption_service
    if _encryption_service is None:
        _encryption_service = EncryptionService()
    return _encryption_service

