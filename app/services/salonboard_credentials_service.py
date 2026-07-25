"""
salonboard_credentials のビジネスロジック。

ログイン情報の暗号化保存・状態確認・自動投稿時の復号を提供する。
- save: 平文を受け取り Fernet で暗号化して保存（upsert）
- get_status: 平文を返さず、設定済みかどうかとメタ情報のみ返す
- get_decrypted_for_posting: 自動投稿処理時にのみ呼び出す。平文を返す
- delete: 設定の削除
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from app.services.salonboard_encryption import get_salonboard_encryption_service
from app.services.supabase_client import get_supabase_client


# 無料で投稿できる回数。これを超えると、課金者/免除者以外はブロックする。
FREE_POST_LIMIT = 1
# 常に課金免除にする対象（既存クライアント等）。DB の is_comped に加えて判定で使う。
COMPED_EMAILS = {"xxx_shun7@icloud.com"}
COMPED_STYLISTS = {"SHUN"}
# 月額サブスクの本番決済リンク。ブロック時にここへ誘導する。
STYLEUP_CHECKOUT_URL = "https://buy.stripe.com/28EdR9e98dJT3ECfav4F200"


def _checkout_url_for(email: str) -> str:
    """決済リンクに登録メールを prefilled_email として付与する。
    こうすると Stripe の支払い画面で登録メールが自動入力され、支払い者が別メールを
    打ち込んで「払ったのに解放されない」事故を防げる（webhook はメールで課金者を照合するため）。"""
    e = (email or "").strip()
    if e:
        return f"{STYLEUP_CHECKOUT_URL}?prefilled_email={quote(e)}"
    return STYLEUP_CHECKOUT_URL


class SalonboardCredentialsService:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.table = "salonboard_credentials"
        self.enc = get_salonboard_encryption_service()

    async def save(
        self,
        device_id: str,
        stylist_name: str,
        login_id: str,
        password: str,
        email: Optional[str] = None,
    ) -> dict:
        """設定の保存。同じ device_id があれば上書き。"""
        encrypted_id = self.enc.encrypt(login_id)
        encrypted_pw = self.enc.encrypt(password)
        consent_at = datetime.now(timezone.utc).isoformat()

        existing = (
            self.supabase.table(self.table)
            .select("id")
            .eq("device_id", device_id)
            .execute()
        )
        if existing.data:
            update_fields = {
                "stylist_name": stylist_name,
                "encrypted_login_id": encrypted_id,
                "encrypted_password": encrypted_pw,
                "consent_at": consent_at,
            }
            if email is not None:
                update_fields["email"] = email
            result = (
                self.supabase.table(self.table)
                .update(update_fields)
                .eq("device_id", device_id)
                .execute()
            )
        else:
            result = (
                self.supabase.table(self.table)
                .insert(
                    {
                        "device_id": device_id,
                        "stylist_name": stylist_name,
                        "email": email,
                        "encrypted_login_id": encrypted_id,
                        "encrypted_password": encrypted_pw,
                        "consent_at": consent_at,
                    }
                )
                .execute()
            )
        return result.data[0] if result.data else {}

    async def get_status(self, device_id: str) -> dict:
        """設定済みかどうかを返す。平文は決して返さない。"""
        result = (
            self.supabase.table(self.table)
            .select("stylist_name, last_used_at, consent_at")
            .eq("device_id", device_id)
            .execute()
        )
        if not result.data:
            return {"has_credentials": False}
        row = result.data[0]
        return {
            "has_credentials": True,
            "stylist_name": row["stylist_name"],
            "last_used_at": row.get("last_used_at"),
            "consent_at": row.get("consent_at"),
        }

    async def get_decrypted_for_posting(self, device_id: str) -> Optional[dict]:
        """自動投稿処理時のみ呼ぶ。平文を返す。
        最後に使用した時刻も更新する。"""
        result = (
            self.supabase.table(self.table)
            .select("*")
            .eq("device_id", device_id)
            .execute()
        )
        if not result.data:
            return None
        row = result.data[0]
        # last_used_at を更新（同期実行で軽い update）
        self.supabase.table(self.table).update(
            {"last_used_at": datetime.now(timezone.utc).isoformat()}
        ).eq("device_id", device_id).execute()
        return {
            "stylist_name": row["stylist_name"],
            "login_id": self.enc.decrypt(row["encrypted_login_id"]),
            "password": self.enc.decrypt(row["encrypted_password"]),
        }

    async def delete(self, device_id: str) -> bool:
        result = (
            self.supabase.table(self.table)
            .delete()
            .eq("device_id", device_id)
            .execute()
        )
        return bool(result.data)

    async def get_entitlement(self, device_id: str) -> dict:
        """投稿してよいか（無料枠・課金・免除）を判定して返す。平文は含まない。"""
        result = (
            self.supabase.table(self.table)
            .select("stylist_name, email, posts_used, is_paid, is_comped")
            .eq("device_id", device_id)
            .execute()
        )
        if not result.data:
            return {
                "has_credentials": False,
                "allowed": False,
                "reason": "not_registered",
                "checkout_url": STYLEUP_CHECKOUT_URL,
            }
        row = result.data[0]
        posts_used = int(row.get("posts_used") or 0)
        email = (row.get("email") or "").strip().lower()
        stylist = (row.get("stylist_name") or "").strip()
        comped = (
            bool(row.get("is_comped"))
            or email in {e.lower() for e in COMPED_EMAILS}
            or stylist in COMPED_STYLISTS
        )
        paid = bool(row.get("is_paid"))
        allowed = comped or paid or posts_used < FREE_POST_LIMIT
        if allowed:
            reason = "comped" if comped else ("paid" if paid else "free")
        else:
            reason = "limit_reached"
        return {
            "has_credentials": True,
            "allowed": allowed,
            "reason": reason,
            "posts_used": posts_used,
            "free_limit": FREE_POST_LIMIT,
            "is_paid": paid,
            "is_comped": comped,
            "checkout_url": None if allowed else _checkout_url_for(email),
        }

    async def increment_posts(self, device_id: str) -> None:
        """投稿成功時に投稿回数を1増やす。"""
        cur = (
            self.supabase.table(self.table)
            .select("posts_used")
            .eq("device_id", device_id)
            .execute()
        )
        if not cur.data:
            return
        n = int(cur.data[0].get("posts_used") or 0) + 1
        self.supabase.table(self.table).update({"posts_used": n}).eq("device_id", device_id).execute()

    async def mark_paid_by_email(self, email: str) -> int:
        """Stripe 決済完了時に、そのメールの利用者を課金済みにする。更新件数を返す。"""
        e = (email or "").strip()
        if not e:
            return 0
        # 大文字小文字を区別せず照合する（登録メールと支払いメールの大小差で
        # 解放漏れが起きないように）。ILIKE をワイルドカードなしで使うと
        # 大文字小文字を無視した完全一致になる。
        res = (
            self.supabase.table(self.table)
            .update({"is_paid": True})
            .ilike("email", e)
            .execute()
        )
        return len(res.data or [])
