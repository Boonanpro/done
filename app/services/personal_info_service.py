"""
PersonalInfoService — ユーザーの個人情報（電話・カード・住所等）を暗号化永続化する。

サービスのログイン認証情報(credentials_service)とは別管理。
- 実値は Fernet 暗号化して personal_info.encrypted_value に保存（平文は持たない）。
- 表示用の masked_hint（非機密）を併存させ、システムプロンプトに常時注入する。
  これにより Dan は「何を保有しているか」を常に認識でき、実値が必要な時だけ
  get_personal_info（復号）で取り出す。

設計の背景:
    電話番号・カード情報を一度渡しても Dan が忘れる問題への根本対策。
    従来は会話中に個人情報を保存する仕組み自体が無く（save_credentials は
    {id,password} のログイン専用）、長期記憶 MEMORY.md もプロンプト非注入だった。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app.services.encryption import get_encryption_service
from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

TABLE_NAME = "personal_info"

# field_key からカテゴリを推論するためのキーワード
_CATEGORY_KEYWORDS = {
    "payment": ("card", "credit", "visa", "master", "amex", "jcb", "iban", "account_number", "bank"),
    "contact": ("phone", "tel", "mobile", "fax", "email", "mail", "line"),
    "address": ("address", "addr", "zip", "postal", "住所", "郵便"),
    "identity": ("birth", "passport", "license", "mynumber", "my_number", "ssn", "insurance"),
}


def infer_category(field_key: str, explicit: str = "") -> str:
    """field_key からカテゴリ(contact/payment/address/identity/other)を推論。"""
    if explicit:
        return explicit
    key = field_key.lower()
    for category, kws in _CATEGORY_KEYWORDS.items():
        if any(kw in key for kw in kws):
            return category
    return "other"


def normalize_field_key(field_key: str) -> str:
    """field_key を正規化（小文字・記号をアンダースコアに）。"""
    s = (field_key or "").strip().lower()
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    return s.strip("_") or "info"


def mask_value(value: str, field_key: str = "", category: str = "") -> str:
    """
    実値から表示用マスク文字列を生成する（非機密）。

    - payment: 末尾4桁を残し他は伏せる（例 "**** **** **** 1234"）
    - contact(電話): 末尾2桁のみ残す（例 "090****6789" → "*******6789"）
    - email: 先頭1文字 + *** + @ドメイン
    - その他: 先頭1文字 + 残りを伏せ字（長さの目安だけ残す）
    """
    if value is None:
        return ""
    value = str(value)
    cat = category or infer_category(field_key)
    key = (field_key or "").lower()

    # クレジットカード等: 数字の末尾4桁
    if cat == "payment" or "card" in key:
        digits = re.sub(r"\D", "", value)
        if len(digits) >= 4:
            return f"**** **** **** {digits[-4:]}"
        return "****"

    # メールアドレス
    if "@" in value and ("mail" in key or "email" in key or cat == "contact"):
        local, _, domain = value.partition("@")
        head = local[0] if local else ""
        return f"{head}***@{domain}"

    # 電話番号
    if cat == "contact" or any(k in key for k in ("phone", "tel", "mobile", "fax")):
        digits = re.sub(r"\D", "", value)
        if len(digits) >= 4:
            return f"{'*' * (len(digits) - 4)}{digits[-4:]}"
        return "****"

    # 汎用: 先頭1文字だけ見せて残りを伏せる
    if len(value) <= 1:
        return "*"
    head = value[0]
    return f"{head}{'*' * min(len(value) - 1, 8)}"


class PersonalInfoService:
    """個人情報の暗号化保存・取得・一覧・削除。"""

    def __init__(self):
        self.encryption = get_encryption_service()
        self.supabase = get_supabase_client().client

    async def save(
        self,
        user_id: str,
        field_key: str,
        value: str,
        category: str = "",
        label: str = "",
    ) -> dict[str, Any]:
        """個人情報を暗号化して保存（user_id + field_key で upsert）。"""
        try:
            field_key = normalize_field_key(field_key)
            category = infer_category(field_key, category)
            masked = mask_value(value, field_key, category)

            encrypted = self.encryption.encrypt_dict({"value": value}).decode("utf-8")

            row = {
                "user_id": user_id,
                "field_key": field_key,
                "category": category,
                "label": label or None,
                "encrypted_value": encrypted,
                "masked_hint": masked,
            }

            existing = (
                self.supabase.table(TABLE_NAME)
                .select("id")
                .eq("user_id", user_id)
                .eq("field_key", field_key)
                .execute()
            )
            if existing.data:
                update = {
                    "category": category,
                    "encrypted_value": encrypted,
                    "masked_hint": masked,
                }
                if label:
                    update["label"] = label
                self.supabase.table(TABLE_NAME).update(update).eq(
                    "user_id", user_id
                ).eq("field_key", field_key).execute()
                logger.info("personal_info updated: user=%s key=%s", user_id, field_key)
            else:
                self.supabase.table(TABLE_NAME).insert(row).execute()
                logger.info("personal_info saved: user=%s key=%s", user_id, field_key)

            return {
                "success": True,
                "field_key": field_key,
                "category": category,
                "masked_hint": masked,
            }
        except Exception as e:
            logger.error("Failed to save personal_info: %s", e)
            return {"success": False, "field_key": field_key, "error": str(e)}

    async def get(self, user_id: str, field_key: str) -> Optional[dict[str, Any]]:
        """個人情報を復号して取得（実値を含む）。"""
        try:
            field_key = normalize_field_key(field_key)
            result = (
                self.supabase.table(TABLE_NAME)
                .select("*")
                .eq("user_id", user_id)
                .eq("field_key", field_key)
                .execute()
            )
            if not result.data:
                return None
            row = result.data[0]
            decrypted = self.encryption.decrypt_dict(
                row["encrypted_value"].encode("utf-8")
            )
            return {
                "field_key": row["field_key"],
                "category": row.get("category"),
                "label": row.get("label"),
                "value": decrypted.get("value"),
                "masked_hint": row.get("masked_hint"),
            }
        except Exception as e:
            logger.error("Failed to get personal_info: %s", e)
            return None

    async def delete(self, user_id: str, field_key: str) -> bool:
        """個人情報を削除。"""
        try:
            field_key = normalize_field_key(field_key)
            result = (
                self.supabase.table(TABLE_NAME)
                .delete()
                .eq("user_id", user_id)
                .eq("field_key", field_key)
                .execute()
            )
            return bool(result.data)
        except Exception as e:
            logger.error("Failed to delete personal_info: %s", e)
            return False

    def list_masked_sync(self, user_id: str) -> list[dict[str, Any]]:
        """
        マスク一覧（field_key, category, label, masked_hint）を同期取得。

        システムプロンプト構築（同期コンテキスト）から呼ぶ。実値の復号は行わない。
        失敗してもプロンプト構築を壊さないよう、例外は握りつぶして空配列を返す。
        """
        try:
            result = (
                self.supabase.table(TABLE_NAME)
                .select("field_key, category, label, masked_hint")
                .eq("user_id", user_id)
                .order("category")
                .execute()
            )
            return result.data or []
        except Exception as e:
            logger.warning("Failed to list personal_info (masked): %s", e)
            return []


# シングルトン
_personal_info_service: Optional[PersonalInfoService] = None


def get_personal_info_service() -> PersonalInfoService:
    global _personal_info_service
    if _personal_info_service is None:
        _personal_info_service = PersonalInfoService()
    return _personal_info_service


def build_personal_info_prompt_section(user_id: str) -> str:
    """
    保存済み個人情報のマスク一覧をシステムプロンプト用に整形して返す。

    値は出さず masked_hint のみ。保有事実を Dan に認識させるのが目的。
    保存が無ければ空文字を返す（セクションごと省略）。
    """
    if not user_id:
        return ""
    try:
        items = get_personal_info_service().list_masked_sync(user_id)
    except Exception:
        return ""
    if not items:
        return ""

    lines = [
        "## 保存済み個人情報（マスク表示・実値は get_personal_info で取得）",
        "",
        "以下はユーザーが過去に教えてくれた個人情報。**既に保有済み**なので、"
        "再度聞き返さずそのまま使ってよい。フォーム入力や予約など実値が必要な操作の"
        "直前に `get_personal_info(field_key)` で復号取得すること。",
        "",
    ]
    for it in items:
        key = it.get("field_key", "")
        label = it.get("label")
        hint = it.get("masked_hint", "")
        suffix = f"（{label}）" if label else ""
        lines.append(f"- `{key}`{suffix}: {hint}")
    return "\n".join(lines)
