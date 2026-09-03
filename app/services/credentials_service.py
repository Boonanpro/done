"""
Credentials Service for Phase 3B: Execution Engine
認証情報の保存・取得・削除を管理するサービス（Supabase永続化）

統一スキーマ（2026/01リファクタリング）:
    全サービス共通で {"id": "...", "password": "..."} の形式を使用。
    保存時・取得時に自動で正規化される。
"""
from typing import Optional, Any, Dict
from datetime import datetime
import logging

from app.services.encryption import get_encryption_service
from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


# ============================================
# 認証情報の正規化（統一スキーマ）
# ============================================

# IDとして認識するキー（優先順）
ID_KEYS = ["id", "email", "member_id", "username", "login_id", "user_id"]
# パスワードとして認識するキー（優先順）
PASSWORD_KEYS = ["password", "pass", "pw"]
# ログインURLとして認識するキー（優先順）
URL_KEYS = ["login_url", "url"]
# 認証アプリ(TOTP)のシードと付随パラメータ。使い捨てのコードではなく、
# コードを生成するための永続的な秘密なのでパスワードと同じ扱いで保管する。
TOTP_KEYS = ["totp_secret", "totp_digits", "totp_period", "totp_algorithm"]


def _host(u: Optional[str]) -> str:
    """URL/ドメイン文字列からホスト名を抽出（小文字・ポート除去）。"""
    from urllib.parse import urlparse
    if not u:
        return ""
    u = u.strip()
    if "://" not in u:
        u = "https://" + u
    return urlparse(u).netloc.lower().split(":")[0]


def _strip_www(host: str) -> str:
    """先頭の www. を落とす（instagram.com と www.instagram.com は同じログイン先）。"""
    return host[4:] if host.startswith("www.") else host


def _base_domain(host: str) -> str:
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _domains_match(h1: str, h2: str) -> bool:
    """2つのホストが同一ログイン先とみなせるか（サブドメイン差は許容）。"""
    if not h1 or not h2:
        return False
    return (
        h1 == h2
        or h1.endswith("." + h2)
        or h2.endswith("." + h1)
        or _base_domain(h1) == _base_domain(h2)
    )


def narrow_url_matches(matches: list) -> list:
    """
    URL照合の結果を絞り込む。

    ベースドメインが同じだけの別サービス（account.line.biz と manager.line.biz 等）が
    混ざることがあるため、ホストまで完全一致した記録があればそちらを優先する。
    それでも複数残る場合は絞り込まない（呼び出し元が service 名で選ぶ）。
    """
    exact = [m for m in matches if m.get("host_exact")]
    return exact if exact else matches


def _normalize_credentials(credentials: Dict[str, Any]) -> Dict[str, Any]:
    """
    認証情報のキー名を統一スキーマに正規化

    入力例:
        {"email": "user@example.com", "password": "xxx"}
        {"member_id": "12345678", "pass": "xxx"}
        {"username": "john", "pw": "xxx"}

    出力（統一形式）:
        {"id": "...", "password": "..."}

    Args:
        credentials: 様々なキー名の認証情報

    Returns:
        正規化された認証情報（id, password のみ）
    """
    normalized: Dict[str, Any] = {}

    # IDを抽出（優先順で最初に見つかったものを使用）
    for key in ID_KEYS:
        if key in credentials and credentials[key]:
            normalized["id"] = credentials[key]
            break

    # パスワードを抽出
    for key in PASSWORD_KEYS:
        if key in credentials and credentials[key]:
            normalized["password"] = credentials[key]
            break

    # _credential_type があればそのまま保持（内部用）
    if "_credential_type" in credentials:
        normalized["_credential_type"] = credentials["_credential_type"]

    # login_url があれば保持（ドメイン照合で正しい認証情報を引くため）
    for key in URL_KEYS:
        if credentials.get(key):
            normalized["login_url"] = credentials[key]
            break

    # 認証アプリのシードがあれば保持（落とすとコード生成ができなくなる）
    for key in TOTP_KEYS:
        if credentials.get(key):
            normalized[key] = credentials[key]

    return normalized


class CredentialsService:
    """認証情報管理サービス（Supabase永続化版）"""

    # 使用するテーブル名（既存のcredentialsテーブルを使用）
    TABLE_NAME = "credentials"

    def __init__(self):
        """サービスを初期化"""
        self.encryption = get_encryption_service()
        self.supabase = get_supabase_client().client

    async def save_credential(
        self,
        user_id: str,
        service: str,
        credentials: dict[str, str],
        credential_type: str = "login",
        login_url: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        認証情報を暗号化して保存

        保存前に正規化を行い、統一スキーマ（id, password）に変換する。

        Args:
            user_id: ユーザーID
            service: サービス名（ex_reservation, amazon, gmail_imap等）
            credentials: 認証情報（email/member_id/username/id, password/pass/pw）
            credential_type: 認証タイプ（login, api_key, oauth, imap）
            login_url: ログインページのURL/ドメイン（例 account.line.biz）。
                       同じメールが複数サービスにある時、ドメイン照合で正しい記録を引くため

        Returns:
            保存結果
        """
        try:
            # 認証情報を正規化（統一スキーマに変換）
            normalized = _normalize_credentials(credentials)

            # credential_typeを追加
            normalized["_credential_type"] = credential_type

            # login_url（明示指定が優先、無ければ credentials 内の値を維持）
            if login_url:
                normalized["login_url"] = login_url

            encrypted_data = self.encryption.encrypt_dict(normalized)
            encrypted_str = encrypted_data.decode('utf-8')  # bytesをstrに変換

            # 既存のレコードを確認
            existing = self.supabase.table(self.TABLE_NAME).select("id").eq(
                "user_id", user_id
            ).eq(
                "service_name", service
            ).execute()

            if existing.data:
                # 更新
                self.supabase.table(self.TABLE_NAME).update({
                    "encrypted_data": encrypted_str,
                }).eq("user_id", user_id).eq("service_name", service).execute()
                logger.info(f"Credentials updated for user {user_id}, service {service}")
            else:
                # 新規作成
                self.supabase.table(self.TABLE_NAME).insert({
                    "user_id": user_id,
                    "service_name": service,
                    "encrypted_data": encrypted_str,
                }).execute()
                logger.info(f"Credentials saved for user {user_id}, service {service}")

            return {
                "success": True,
                "service": service,
                "message": "Credentials saved",
            }
        except Exception as e:
            logger.error(f"Failed to save credentials: {e}")
            return {
                "success": False,
                "service": service,
                "message": str(e),
            }

    async def save_totp_secret(
        self,
        user_id: str,
        service: str,
        secret: str,
        digits: int = 6,
        period: int = 30,
        algorithm: str = "SHA1",
        login_url: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        認証アプリ(TOTP)のシードを保存する。

        save_credential は渡された辞書で暗号化データを丸ごと置き換えるため、
        シードだけを渡すと保存済みのID/パスワードが消える。ここでは既存レコードを
        読んでから統合して書き戻すので、パスワードを保持したままシードを追加できる。

        Args:
            user_id: ユーザーID
            service: サービス名
            secret: base32 のシード（正規化済みを渡すこと）
            digits/period/algorithm: 認証アプリのパラメータ
            login_url: ログインページのURL/ドメイン（URL照合用）

        Returns:
            保存結果
        """
        try:
            existing = await self.get_credential(user_id, service)

            merged: Dict[str, Any] = {
                "totp_secret": secret,
                "totp_digits": digits,
                "totp_period": period,
                "totp_algorithm": algorithm,
            }
            credential_type = "login"
            if existing:
                # 既存のID/パスワード/URLを引き継ぐ（消さない）
                if existing.get("id"):
                    merged["id"] = existing["id"]
                if existing.get("password"):
                    merged["password"] = existing["password"]
                if existing.get("login_url"):
                    merged["login_url"] = existing["login_url"]
                credential_type = existing.get("credential_type") or "login"

            return await self.save_credential(
                user_id=user_id,
                service=service,
                credentials=merged,
                credential_type=credential_type,
                login_url=login_url,
            )
        except Exception as e:
            logger.error(f"Failed to save TOTP secret: {e}")
            return {"success": False, "service": service, "message": str(e)}

    async def get_credential(
        self,
        user_id: str,
        service: str,
    ) -> Optional[dict[str, Any]]:
        """
        認証情報を取得して復号

        取得時も正規化を行い、統一スキーマ（id, password）で返す。
        マイグレーション前の旧データにも対応。

        Args:
            user_id: ユーザーID
            service: サービス名

        Returns:
            正規化された認証情報（id, password）、なければNone
        """
        try:
            result = self.supabase.table(self.TABLE_NAME).select("*").eq(
                "user_id", user_id
            ).eq(
                "service_name", service
            ).execute()

            if not result.data:
                return None

            stored = result.data[0]
            encrypted_bytes = stored["encrypted_data"].encode('utf-8')
            decrypted = self.encryption.decrypt_dict(encrypted_bytes)

            # _credential_typeを取り出してトップレベルに
            credential_type = decrypted.pop("_credential_type", "login")

            # 正規化して統一スキーマに変換（旧データ対応）
            normalized = _normalize_credentials(decrypted)

            return {
                "id": normalized.get("id"),
                "password": normalized.get("password"),
                "service": stored["service_name"],
                "credential_type": credential_type,
                "login_url": normalized.get("login_url"),
                "totp_secret": normalized.get("totp_secret"),
                "totp_digits": normalized.get("totp_digits"),
                "totp_period": normalized.get("totp_period"),
                "totp_algorithm": normalized.get("totp_algorithm"),
            }
        except Exception as e:
            logger.error(f"Failed to get credentials: {e}")
            return None

    async def find_credentials_by_url(
        self,
        user_id: str,
        url: str,
    ) -> list[dict[str, Any]]:
        """
        ログインページのURL/ドメインに一致する認証情報を「全件」返す。

        同じドメインに複数アカウントを保存していることがある（例: Instagram の
        個人用と事業用）。1件目を黙って返すと別アカウントのパスワードを
        使ってしまうため、照合結果は全件返し、どれを使うかは呼び出し元が決める。

        Args:
            user_id: ユーザーID
            url: 現在のログインページURL（例 https://account.line.biz/login）

        Returns:
            一致した認証情報のリスト（id, password, service, credential_type, login_url）
        """
        target = _host(url)
        if not target:
            return []
        matches: list[dict[str, Any]] = []
        try:
            result = self.supabase.table(self.TABLE_NAME).select("*").eq(
                "user_id", user_id
            ).execute()
            for row in result.data:
                try:
                    decrypted = self.encryption.decrypt_dict(
                        row["encrypted_data"].encode("utf-8")
                    )
                except Exception:
                    continue
                stored_url = decrypted.get("login_url")
                if not stored_url or not _domains_match(target, _host(stored_url)):
                    continue
                credential_type = decrypted.pop("_credential_type", "login")
                normalized = _normalize_credentials(decrypted)
                matches.append({
                    "id": normalized.get("id"),
                    "password": normalized.get("password"),
                    "service": row["service_name"],
                    "credential_type": credential_type,
                    "login_url": stored_url,
                    "totp_secret": normalized.get("totp_secret"),
                    "totp_digits": normalized.get("totp_digits"),
                    "totp_period": normalized.get("totp_period"),
                    "totp_algorithm": normalized.get("totp_algorithm"),
                    # ホストまで同じか（ベースドメインだけ同じ別サービスと区別する）。
                    # www の有無は同じログイン先なので無視する。
                    "host_exact": _strip_www(_host(stored_url)) == _strip_www(target),
                })
            return matches
        except Exception as e:
            logger.error(f"Failed to find credentials by url: {e}")
            return []

    async def find_credential_by_url(
        self,
        user_id: str,
        url: str,
    ) -> Optional[dict[str, Any]]:
        """
        URL照合で一意に定まる場合だけ、その1件を返す。

        複数一致した場合は None を返す（どれか1つを勝手に選ぶと別アカウントの
        パスワードを使ってしまうため）。呼び出し元は service 名で指定し直すこと。
        """
        matches = narrow_url_matches(await self.find_credentials_by_url(user_id, url))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            logger.warning(
                "URL %s に複数の認証情報が一致: %s — service 名の指定が必要",
                url,
                [m.get("service") for m in matches],
            )
        return None

    async def list_credentials(
        self,
        user_id: str,
    ) -> list[dict[str, Any]]:
        """
        ユーザーの保存済みサービス一覧を取得

        Args:
            user_id: ユーザーID

        Returns:
            保存済みサービス一覧（認証情報は含まない）
        """
        try:
            result = self.supabase.table(self.TABLE_NAME).select(
                "id, service_name, created_at, updated_at"
            ).eq("user_id", user_id).execute()

            return [
                {
                    "service": row["service_name"],
                    "created_at": row["created_at"],
                    "updated_at": row.get("updated_at"),
                }
                for row in result.data
            ]
        except Exception as e:
            logger.error(f"Failed to list credentials: {e}")
            return []

    async def delete_credential(
        self,
        user_id: str,
        service: str,
    ) -> dict[str, Any]:
        """
        認証情報を削除

        Args:
            user_id: ユーザーID
            service: サービス名

        Returns:
            削除結果
        """
        try:
            result = self.supabase.table(self.TABLE_NAME).delete().eq(
                "user_id", user_id
            ).eq(
                "service_name", service
            ).execute()

            if result.data:
                logger.info(f"Credentials deleted for user {user_id}, service {service}")
                return {
                    "success": True,
                    "service": service,
                    "message": "Credentials deleted",
                }
            else:
                return {
                    "success": False,
                    "service": service,
                    "message": "Credentials not found",
                }
        except Exception as e:
            logger.error(f"Failed to delete credentials: {e}")
            return {
                "success": False,
                "service": service,
                "message": str(e),
            }

    async def has_credential(
        self,
        user_id: str,
        service: str,
    ) -> bool:
        """
        認証情報が存在するかチェック

        Args:
            user_id: ユーザーID
            service: サービス名

        Returns:
            存在する場合True
        """
        try:
            result = self.supabase.table(self.TABLE_NAME).select("id").eq(
                "user_id", user_id
            ).eq(
                "service_name", service
            ).execute()

            return bool(result.data)
        except Exception as e:
            logger.error(f"Failed to check credentials: {e}")
            return False


# シングルトンインスタンス
_credentials_service: Optional[CredentialsService] = None


def get_credentials_service() -> CredentialsService:
    """認証情報サービスのシングルトンインスタンスを取得"""
    global _credentials_service
    if _credentials_service is None:
        _credentials_service = CredentialsService()
    return _credentials_service
