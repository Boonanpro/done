#!/usr/bin/env python
"""
認証情報スキーマ マイグレーションスクリプト

既存のcredentialsテーブルのデータを統一スキーマに変換する。

旧スキーマ:
    {"email": "...", "password": "..."} または
    {"member_id": "...", "password": "..."} または
    {"username": "...", "pass": "..."}

新スキーマ（統一）:
    {"id": "...", "password": "..."}

使用方法:
    # 変更内容を確認（実行しない）
    python scripts/migrate_credentials_schema.py --dry-run

    # 実際にマイグレーションを実行
    python scripts/migrate_credentials_schema.py
"""

import asyncio
import argparse
import logging
from typing import Dict, Any

# プロジェクトルートをパスに追加
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.encryption import get_encryption_service
from app.services.supabase_client import get_supabase_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# IDとして認識するキー（優先順）
ID_KEYS = ["id", "email", "member_id", "username", "login_id", "user_id"]
# パスワードとして認識するキー（優先順）
PASSWORD_KEYS = ["password", "pass", "pw"]


def normalize_credentials(credentials: Dict[str, Any]) -> Dict[str, Any]:
    """認証情報を統一スキーマに正規化"""
    normalized: Dict[str, Any] = {}

    # IDを抽出
    for key in ID_KEYS:
        if key in credentials and credentials[key]:
            normalized["id"] = credentials[key]
            break

    # パスワードを抽出
    for key in PASSWORD_KEYS:
        if key in credentials and credentials[key]:
            normalized["password"] = credentials[key]
            break

    # _credential_type があれば保持
    if "_credential_type" in credentials:
        normalized["_credential_type"] = credentials["_credential_type"]

    return normalized


def is_already_normalized(credentials: Dict[str, Any]) -> bool:
    """既に統一スキーマかどうかをチェック"""
    # "id" と "password" のみ（+ _credential_type）であれば正規化済み
    allowed_keys = {"id", "password", "_credential_type"}
    actual_keys = set(credentials.keys())
    return actual_keys.issubset(allowed_keys) and "id" in credentials


async def migrate_credentials(dry_run: bool = False) -> Dict[str, Any]:
    """
    全ての認証情報を統一スキーマにマイグレーション

    Args:
        dry_run: Trueの場合、変更内容を表示するだけで実行しない

    Returns:
        マイグレーション結果
    """
    encryption = get_encryption_service()
    supabase = get_supabase_client().client

    stats = {
        "total": 0,
        "already_normalized": 0,
        "migrated": 0,
        "errors": 0,
        "details": [],
    }

    try:
        # 全てのcredentialsを取得
        result = supabase.table("credentials").select("*").execute()

        if not result.data:
            logger.info("credentialsテーブルにデータがありません")
            return stats

        stats["total"] = len(result.data)
        logger.info(f"処理対象: {stats['total']}件")

        for row in result.data:
            row_id = row["id"]
            user_id = row["user_id"]
            service = row["service_name"]

            try:
                # 復号
                encrypted_bytes = row["encrypted_data"].encode('utf-8')
                decrypted = encryption.decrypt_dict(encrypted_bytes)

                # 既に正規化済みかチェック
                if is_already_normalized(decrypted):
                    stats["already_normalized"] += 1
                    logger.debug(f"  [{row_id}] {service}: 既に正規化済み")
                    continue

                # 正規化
                normalized = normalize_credentials(decrypted)

                # 変更内容を記録
                change_info = {
                    "row_id": row_id,
                    "user_id": user_id,
                    "service": service,
                    "before_keys": list(decrypted.keys()),
                    "after_keys": list(normalized.keys()),
                }
                stats["details"].append(change_info)

                logger.info(
                    f"  [{row_id}] {service}: "
                    f"{list(decrypted.keys())} → {list(normalized.keys())}"
                )

                if not dry_run:
                    # 再暗号化
                    encrypted_data = encryption.encrypt_dict(normalized)
                    encrypted_str = encrypted_data.decode('utf-8')

                    # 更新
                    supabase.table("credentials").update({
                        "encrypted_data": encrypted_str,
                    }).eq("id", row_id).execute()

                    logger.info(f"  [{row_id}] {service}: マイグレーション完了")

                stats["migrated"] += 1

            except Exception as e:
                stats["errors"] += 1
                logger.error(f"  [{row_id}] {service}: エラー - {e}")
                continue

    except Exception as e:
        logger.error(f"マイグレーション全体エラー: {e}")
        raise

    return stats


def print_summary(stats: Dict[str, Any], dry_run: bool):
    """結果サマリーを表示"""
    print("\n" + "=" * 50)
    if dry_run:
        print("マイグレーション プレビュー（dry-run）")
    else:
        print("マイグレーション 完了")
    print("=" * 50)
    print(f"対象レコード数: {stats['total']}")
    print(f"既に正規化済み: {stats['already_normalized']}")
    print(f"マイグレーション{'対象' if dry_run else '完了'}: {stats['migrated']}")
    print(f"エラー: {stats['errors']}")
    print("=" * 50)

    if dry_run and stats['migrated'] > 0:
        print("\n実際にマイグレーションを実行するには:")
        print("  python scripts/migrate_credentials_schema.py")


def main():
    parser = argparse.ArgumentParser(
        description="認証情報を統一スキーマにマイグレーション"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="変更内容を表示するだけで実行しない",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="詳細ログを表示",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info(f"マイグレーション開始 (dry_run={args.dry_run})")

    stats = asyncio.run(migrate_credentials(dry_run=args.dry_run))

    print_summary(stats, args.dry_run)


if __name__ == "__main__":
    main()
