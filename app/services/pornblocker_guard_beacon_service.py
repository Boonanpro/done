"""
ポルノブロッカー端末の「守りが立っているか」を受け取って残す。

【この仕組みが要る理由】
遮断の精度をいくら上げても、遮断そのものが止まっていれば意味が無い。
そして守りを外した本人は、外れていることを運営に言わない。

Android の作り上「絶対に破れない」は作れない。だから
「破ったら必ず分かる」でふさぐ。ここはその受け皿。

【残すもの・残さないもの】
残すのは守りが立っているかどうかだけ。
見たサイト・検索語・止めた画像は受け取りもしないし残さない。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.services.supabase_client import get_supabase_client

# 守りの部品。テーブルの列名と端末が送ってくるキーが 1 対 1 で対応する。
FLAG_FIELDS = (
    "protected",
    "guard",
    "overlay",
    "vpn",
    "admin",
    "notifications",
    "locked",
    "safe_mode",
)

#: これだけ音沙汰が無ければ「消息不明」とみなす。
#:
#: 端末は 30 分ごとに知らせを送る。2 時間空くのは、
#: 電源が切れている・圏外が続いている・アプリが消された、のいずれか。
#: どれも運営が知っておくべき状態なので、まとめて拾う。
#: 短くすると、地下鉄や機内モードで毎回騒ぐことになる。
SILENT_AFTER_MINUTES = 120


class PornblockerGuardBeaconService:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.devices = "pornblocker_devices"
        self.events = "pornblocker_events"

    # ------------------------------------------------------------ 端末から

    async def ingest(self, events: List[Dict[str, Any]]) -> int:
        """
        端末から届いた知らせを残す。

        履歴は届いた分すべてを残す（圏外で溜まっていた分も含む）。
        最新の状態は、そのうち一番新しいものだけで上書きする。
        途中の古い知らせで上書きすると、復帰した端末が
        「外れている」状態のまま一覧に残ってしまう。
        """
        if not events:
            return 0

        rows = [self._to_event_row(e) for e in events]
        self.supabase.table(self.events).insert(rows).execute()

        newest = max(events, key=lambda e: e.get("at") or 0)
        await self._upsert_device(newest)
        return len(rows)

    def _to_event_row(self, e: Dict[str, Any]) -> Dict[str, Any]:
        row = {k: bool(e.get(k, False)) for k in FLAG_FIELDS}
        row.update(
            device_id=e["device_id"],
            reported_at=_from_millis(e.get("at")),
            app_version=e.get("app_version"),
            model=e.get("model"),
            android=e.get("android"),
        )
        return row

    async def _upsert_device(self, e: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        row = {k: bool(e.get(k, False)) for k in FLAG_FIELDS}
        row.update(
            device_id=e["device_id"],
            last_seen_at=now,
            updated_at=now,
            reported_at=_from_millis(e.get("at")),
            app_version=e.get("app_version"),
            model=e.get("model"),
            android=e.get("android"),
        )
        # first_seen_at は既にある行を上書きしない。
        # 上書きすると「いつから使っているか」が毎回今になって消える。
        existing = (
            self.supabase.table(self.devices)
            .select("device_id")
            .eq("device_id", e["device_id"])
            .execute()
        )
        if existing.data:
            self.supabase.table(self.devices).update(row).eq(
                "device_id", e["device_id"]
            ).execute()
        else:
            row["first_seen_at"] = now
            self.supabase.table(self.devices).insert(row).execute()

    # ------------------------------------------------------------ 運営から

    async def list_devices(self) -> List[Dict[str, Any]]:
        """
        一覧。手を打つべき端末が上に来るように並べる。

        並べ替えを画面側に任せない。運営が見るのは
        「今どれが危ないか」であって、名前順でも時刻順でもないため。
        """
        result = (
            self.supabase.table(self.devices)
            .select("*")
            .order("last_seen_at", desc=True)
            .execute()
        )
        rows = result.data or []
        now = datetime.now(timezone.utc)

        for r in rows:
            minutes = _minutes_since(r.get("last_seen_at"), now)
            r["minutes_since_seen"] = minutes
            r["silent"] = minutes is None or minutes >= SILENT_AFTER_MINUTES
            # 守りが欠けている、連絡が途絶えている、
            # ロック中なのに消せる状態、のどれかなら運営の出番。
            r["needs_attention"] = (
                not r.get("protected")
                or r["silent"]
                or (r.get("locked") and not r.get("admin"))
            )

        rows.sort(
            key=lambda r: (
                not r["needs_attention"],          # 要対応を先頭へ
                -(r["minutes_since_seen"] or 0),   # 音沙汰が無いものほど先
            )
        )
        return rows

    async def list_events(self, device_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        result = (
            self.supabase.table(self.events)
            .select("*")
            .eq("device_id", device_id)
            .order("received_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    async def update_label(
        self, device_id: str, label: Optional[str], contact: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """運営が端末に呼び名と連絡先を付ける。誰の端末か分からないと連絡できない。"""
        patch: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if label is not None:
            patch["label"] = label
        if contact is not None:
            patch["contact"] = contact
        result = (
            self.supabase.table(self.devices)
            .update(patch)
            .eq("device_id", device_id)
            .execute()
        )
        return result.data[0] if result.data else None


def _from_millis(ms: Optional[int]) -> Optional[str]:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        # 端末の時計が壊れていても、知らせ自体は捨てない。
        return None


def _minutes_since(iso: Optional[str], now: datetime) -> Optional[int]:
    if not iso:
        return None
    try:
        seen = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return max(0, int((now - seen) / timedelta(minutes=1)))


# ================================================================== 課金と連絡


class PornblockerBillingService:
    """
    鍵の対価（月額）と、やめたい人からの連絡を扱う。

    【なぜ「鍵」に課金するのか】
    遮断そのものは無料で配る。止まることは、入れてすぐ体験してもらう必要がある。
    お金をもらうのは **本人が自分で外せなくすること** に対して。
    自分で外せる鍵は、夜中に思い立てば 30 秒で外せる。それでは効かない。
    外す手段をこちらが預かる。そこが商品。

    【解約を「連絡」にしている理由】
    鍵を外せるのが運営だけなら、やめたい人は必ずこちらへ来る。
    そこを一方通行のフォームにすると、送って終わりになって話が途切れる。
    やめたい人と話せる場所は、そのまま引き止められる場所でもある。
    """

    #: 契約が生きているとみなす Stripe 側の状態。
    #:
    #: past_due（引き落とし失敗）を含めているのは、カードの期限切れで
    #: 数日後に復帰する人が大半だから。ここで即座に鍵を外すと、
    #: 一番外れてほしくない瞬間（本人が弱っている時期）に無防備になる。
    ACTIVE_STATUSES = ("active", "trialing", "past_due")

    def __init__(self):
        self.supabase = get_supabase_client().client
        self.subs = "pornblocker_subscriptions"
        self.messages = "pornblocker_messages"

    # ------------------------------------------------------------ 契約

    def is_configured(self) -> bool:
        from app.config import settings

        return bool(settings.PORNBLOCKER_STRIPE_SECRET_KEY and settings.PORNBLOCKER_STRIPE_PRICE_ID)

    async def get_status(self, device_id: str) -> Dict[str, Any]:
        result = (
            self.supabase.table(self.subs)
            .select("*")
            .eq("device_id", device_id)
            .execute()
        )
        row = result.data[0] if result.data else None
        if not row:
            return {"active": False, "status": "none", "current_period_end": None}
        return {
            "active": row.get("status") in self.ACTIVE_STATUSES,
            "status": row.get("status") or "none",
            "current_period_end": row.get("current_period_end"),
        }

    async def create_checkout(self, device_id: str) -> Optional[str]:
        """
        支払いのページを作って、その住所を返す。

        端末の呼び名（device_id）を Stripe 側にも持たせる。
        webhook が返ってきたときに、どの端末の鍵かを引き当てる唯一の手掛かり。
        """
        from app.config import settings

        if not self.is_configured():
            return None

        import stripe

        stripe.api_key = settings.PORNBLOCKER_STRIPE_SECRET_KEY
        return_url = settings.PORNBLOCKER_CHECKOUT_RETURN_URL or "https://example.com/thanks"

        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": settings.PORNBLOCKER_STRIPE_PRICE_ID, "quantity": 1}],
            client_reference_id=device_id,
            metadata={"device_id": device_id},
            subscription_data={"metadata": {"device_id": device_id}},
            success_url=return_url,
            cancel_url=return_url,
        )
        # 支払いが終わる前でも行を作っておく。作らないと、webhook が
        # 何かの理由で届かなかったときに「払ったのに何も残っていない」になる。
        await self._upsert(device_id, {"status": "pending", "checkout_session_id": session.id})
        return session.url

    async def apply_stripe_event(self, event: Dict[str, Any]) -> bool:
        """
        Stripe からの知らせを契約状態に反映する。

        扱うのは「契約が始まった・変わった・終わった」の 3 つだけ。
        支払い 1 回ごとの成否は Stripe 側が状態にまとめてくれるので、こちらで数えない。
        """
        kind = event.get("type") or ""
        obj = (event.get("data") or {}).get("object") or {}

        device_id = (obj.get("metadata") or {}).get("device_id") or obj.get("client_reference_id")
        if not device_id:
            return False

        if kind == "checkout.session.completed":
            await self._upsert(
                device_id,
                {
                    "status": "active",
                    "stripe_customer_id": obj.get("customer"),
                    "stripe_subscription_id": obj.get("subscription"),
                },
            )
            return True

        if kind in ("customer.subscription.updated", "customer.subscription.created"):
            await self._upsert(
                device_id,
                {
                    "status": obj.get("status") or "unknown",
                    "stripe_customer_id": obj.get("customer"),
                    "stripe_subscription_id": obj.get("id"),
                    "current_period_end": _from_seconds(obj.get("current_period_end")),
                },
            )
            return True

        if kind == "customer.subscription.deleted":
            await self._upsert(device_id, {"status": "canceled"})
            return True

        return False

    async def _upsert(self, device_id: str, patch: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        patch = {k: v for k, v in patch.items() if v is not None}
        patch["updated_at"] = now

        existing = (
            self.supabase.table(self.subs)
            .select("device_id")
            .eq("device_id", device_id)
            .execute()
        )
        if existing.data:
            self.supabase.table(self.subs).update(patch).eq("device_id", device_id).execute()
        else:
            patch.update(device_id=device_id, created_at=now)
            self.supabase.table(self.subs).insert(patch).execute()

    # ------------------------------------------------------------ 連絡

    async def list_messages(self, device_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        result = (
            self.supabase.table(self.messages)
            .select("*")
            .eq("device_id", device_id)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data or []

    async def add_message(self, device_id: str, sender: str, text: str) -> Dict[str, Any]:
        row = {
            "device_id": device_id,
            "sender": sender,
            "text": text[:4000],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        result = self.supabase.table(self.messages).insert(row).execute()
        return result.data[0] if result.data else row

    async def list_threads(self) -> List[Dict[str, Any]]:
        """
        運営が見る一覧。**返事をしていないものが先頭に来る。**

        やめたい人からの連絡を放置するのが一番まずい。並べ替えを画面に任せない。
        """
        result = (
            self.supabase.table(self.messages)
            .select("*")
            .order("created_at", desc=True)
            .limit(1000)
            .execute()
        )
        rows = result.data or []

        threads: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            t = threads.setdefault(
                r["device_id"],
                {"device_id": r["device_id"], "last_text": r["text"], "last_at": r["created_at"], "count": 0},
            )
            t["count"] += 1
            # 降順で来るので、最初に見た「利用者の発言」が最新。
            if "awaiting_reply" not in t:
                t["awaiting_reply"] = r.get("sender") == "user"
        return sorted(
            threads.values(),
            key=lambda t: (not t.get("awaiting_reply"), t["last_at"]),
            reverse=False,
        )


def _from_seconds(sec: Optional[int]) -> Optional[str]:
    if not sec:
        return None
    try:
        return datetime.fromtimestamp(sec, tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return None
