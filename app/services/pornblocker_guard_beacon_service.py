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
    "secure_space",
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
                # もう一つの領域（セキュアフォルダ）が使われている。守りが効かない場所がある
                or bool(r.get("secure_space"))
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


# ================================================================== 運営への知らせ（見回り）
#
# 【なぜ要るのか】
# 端末は 30 分ごとに「守りが立っている」と送ってくる。2 時間途切れると一覧では
# 「消息不明」と出るが、**一覧を開いた人にしか見えない**。アプリを消された・機種変した・
# 初期化された・セーフモードで起動された、のどれも、誰かが見に行くまで分からなかった。
#
# ここは、その一覧を代わりに見に行って、変わった瞬間だけ運営（みきさん）の部屋へ知らせる。
# 知らせるのは「変わったとき」だけ。同じ状態が続いている間は黙る。戻ったら 1 回だけ「戻りました」。
#
# 【なぜダン側なのか】
# 端末が話しかける先（Cloud Run）は、呼ばれたときだけ動く作りで、自分から時計を見ない。
# 「来なくなった」ことは、誰かが時計を見て初めて分かる。常に動いているのはダン側なので、ここで見る。
# 知らせたかどうかは pornblocker_devices.alert_state に残す。残さないと、ダンが再起動するたびに
# 同じ知らせをもう一度送ってしまう。

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

#: 知らせの持ち主（みきさん）。
ALERT_USER_ID = os.getenv("PORNBLOCKER_ALERT_USER_ID", "2582a188-ff24-4a4f-b989-6063034d90b2")
#: 知らせを入れる部屋。
#: 最初は事業の相談部屋（a588ca6f…）へ入れていたが、「相談の流れに見回りの履歴が混ざってうざい」
#: とのことで（2026-09-06）、サイドバーに専用チャット「ポルノブロッカー見回り」を 1 つ作ってそこへ入れる。
#: 環境変数で部屋を固定したいときだけ PORNBLOCKER_ALERT_ROOM_ID を指定する。
ALERT_ROOM_ID = os.getenv("PORNBLOCKER_ALERT_ROOM_ID", "")
ALERT_ROOM_TITLE = os.getenv("PORNBLOCKER_ALERT_ROOM_TITLE", "ポルノブロッカー見回り")
ALERT_ROOM_DESCRIPTION = (
    "ポルノブロッカーの端末を 5 分ごとに見回り、変わったときだけここへ知らせる専用の部屋です。"
    "（合図が 2 時間・24 時間途切れた／戻った／守りが外れた／鍵があるのに消せる／セキュアフォルダがある）"
    "同じ状態が続く間は黙ります。事業の相談は元の部屋で行い、この部屋は記録用です。"
)
_alert_room_cache: Optional[str] = None


async def resolve_alert_room() -> str:
    """知らせを入れる部屋の ID を返す。専用チャットが無ければ 1 回だけ作る。"""
    global _alert_room_cache
    if ALERT_ROOM_ID:
        return ALERT_ROOM_ID
    if _alert_room_cache:
        return _alert_room_cache

    def _find() -> Optional[str]:
        r = (
            get_supabase_client().client.table("projects")
            .select("room_id, created_at")
            .eq("user_id", ALERT_USER_ID)
            .eq("title", ALERT_ROOM_TITLE)
            .order("created_at")
            .limit(1)
            .execute()
        )
        rows = r.data or []
        return str(rows[0]["room_id"]) if rows and rows[0].get("room_id") else None

    room_id = await asyncio.to_thread(_find)
    if not room_id:
        from app.services.project_service import ProjectService

        project = await ProjectService().create_project(
            user_id=ALERT_USER_ID, title=ALERT_ROOM_TITLE, description=ALERT_ROOM_DESCRIPTION,
        )
        room_id = project.get("room_id")
        if not room_id:
            raise RuntimeError("見回り用の部屋を作れませんでした（room_id が空）")
        from app.services.chat_service import ChatService

        await ChatService().send_dan_ai_message(ALERT_USER_ID, ALERT_ROOM_DESCRIPTION, room_id=room_id)
        logger.info("pornblocker alert room created: %s", room_id)
    _alert_room_cache = room_id
    return room_id
#: 見回りの間隔（秒）。端末は 30 分ごとなので、5 分で見れば十分に早い。
ALERT_POLL_SECONDS = int(os.getenv("PORNBLOCKER_ALERT_POLL_SECONDS", "300"))
#: 2 時間の知らせのあと、これだけ経っても戻らなければもう 1 回だけ知らせる。
LONG_SILENT_MINUTES = 24 * 60
#: これより前から音沙汰が無い端末は「もう使われていない」とみなして知らせない。
#: 試験に使った端末や、消したまま放置された端末で、初回の見回りが鳴りっぱなしになるのを防ぐ。
STALE_AFTER_MINUTES = 3 * 24 * 60


def _device_name(r: Dict[str, Any]) -> str:
    label = (r.get("label") or "").strip()
    short = str(r.get("device_id") or "")[:8]
    model = (r.get("model") or "").replace("samsung", "Galaxy").strip()
    head = label or f"端末 {short}"
    ver = f"v{r.get('app_version')}" if r.get("app_version") else ""
    tail = " / ".join(x for x in (model, ver) if x)
    return f"{head}（{tail}）" if tail else head


def plan_alerts(rows: List[Dict[str, Any]], now: datetime) -> List[Dict[str, Any]]:
    """
    一覧を見て「いま送るべき知らせ」と「更新する alert_state」を決める。

    端末の部品を一切使わない（送りもしない）。だから実際に送らずに確かめられる。
    返すのは 1 台につき {"device_id", "state", "messages": [文]} で、messages が空なら送るものは無い。
    """
    out: List[Dict[str, Any]] = []
    for r in rows:
        state = dict(r.get("alert_state") or {})
        before = dict(state)
        msgs: List[str] = []
        name = _device_name(r)
        minutes = _minutes_since(r.get("last_seen_at"), now)
        silent = minutes is None or minutes >= SILENT_AFTER_MINUTES
        stamp = now.isoformat()

        # ---- 合図が途切れた / 戻った
        if silent:
            if (minutes is None or minutes >= STALE_AFTER_MINUTES) and not state.get("silent"):
                # 昔から途絶えている端末。知らせずに「見た」印だけ付ける。
                state["silent"] = "stale"
            elif not state.get("silent"):
                state["silent"] = stamp
                hours = f"{minutes // 60}" if minutes is not None else "?"
                msgs.append(
                    f"{name} から守りの合図が {hours} 時間届いていません。"
                    "アプリを消した・機種変した・電源を切ったまま、のどれかの可能性があります。"
                )
            elif (
                state.get("silent") != "stale"
                and not state.get("silent_long")
                and minutes is not None
                and minutes >= LONG_SILENT_MINUTES
            ):
                state["silent_long"] = stamp
                msgs.append(f"{name} の合図が途切れて 24 時間たちました。本人に連絡したほうがよさそうです。")
        else:
            if state.get("silent") and state.get("silent") != "stale":
                msgs.append(f"{name} の合図が戻りました。")
            state.pop("silent", None)
            state.pop("silent_long", None)

        # 合図が来ている端末についてだけ、中身の状態を見る（来ていないものは中身も古い）
        if not silent:
            checks = (
                ("unprotected", not r.get("protected"),
                 f"{name} の守りが外れています（見張り・遮断のどれかが止まっています）。",
                 f"{name} の守りが立ち直りました。"),
                ("lock_incomplete", bool(r.get("locked")) and not r.get("admin"),
                 f"{name} は鍵がかかっているのに、アプリを消せる状態です。",
                 f"{name} は鍵と消せない設定がそろいました。"),
                ("secure_space", bool(r.get("secure_space")),
                 f"{name} でセキュアフォルダ（もう一つの領域）が使われています。そこにはこの守りが効きません。",
                 f"{name} のセキュアフォルダは使われなくなりました。"),
            )
            for key, active, on_text, off_text in checks:
                if active and not state.get(key):
                    state[key] = stamp
                    msgs.append(on_text)
                elif not active and state.get(key):
                    state.pop(key, None)
                    msgs.append(off_text)

        if msgs or state != before:
            out.append({"device_id": r["device_id"], "state": state, "messages": msgs})
    return out


class PornblockerAlertWatcher:
    """見回り本体。一覧を読み、変わった端末だけ部屋へ知らせ、alert_state を書き戻す。"""

    def __init__(self) -> None:
        self.beacons = PornblockerGuardBeaconService()

    async def run_once(self, dry_run: bool = False) -> List[str]:
        rows = await self.beacons.list_devices()
        plans = plan_alerts(rows, datetime.now(timezone.utc))
        sent: List[str] = []
        for plan in plans:
            if plan["messages"] and not dry_run:
                text = "ポルノブロッカーの見回り\n" + "\n".join(f"- {m}" for m in plan["messages"])
                await self._notify(text)
            sent.extend(plan["messages"])
            if not dry_run:
                self.beacons.supabase.table(self.beacons.devices).update(
                    {"alert_state": plan["state"]}
                ).eq("device_id", plan["device_id"]).execute()
        return sent

    async def _notify(self, text: str) -> None:
        from app.services.chat_service import ChatService

        room_id = await resolve_alert_room()
        await ChatService().send_dan_ai_message(ALERT_USER_ID, text, room_id=room_id)
        try:
            from app.services.push_service import get_push_service

            svc = get_push_service()
            body = text.split("\n", 1)[1][:120] if "\n" in text else text[:120]
            await svc.notify_room(
                room_id=f"user:{ALERT_USER_ID}", exclude_type="ai",
                title="ポルノブロッカー", body=body, url=f"/chat/{room_id}",
            )
        except Exception as e:
            logger.debug("pornblocker alert push skipped: %s", e)


_watcher_started = False


async def _alert_loop() -> None:
    await asyncio.sleep(20)
    while True:
        try:
            sent = await PornblockerAlertWatcher().run_once()
            if sent:
                logger.info("pornblocker alerts sent: %d", len(sent))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("pornblocker alert cycle failed: %s", e)
        await asyncio.sleep(ALERT_POLL_SECONDS)


def start_alert_watcher() -> Optional["asyncio.Task"]:
    """sandbox の起動時に 1 回だけ呼ぶ。"""
    global _watcher_started
    if _watcher_started:
        return None
    _watcher_started = True
    task = asyncio.get_event_loop().create_task(_alert_loop())
    logger.info("pornblocker alert watcher started (interval=%ss)", ALERT_POLL_SECONDS)
    return task


def _from_millis(ms: Optional[int]) -> Optional[str]:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        # 端末の時計が壊れていても、知らせ自体は捨てない。
        return None


def _normalize_iso(iso: str) -> str:
    """
    保存先が返す時刻の小数部は 5 桁のことがあり（例 04:55:53.85578+00:00）、
    Python 3.10 の fromisoformat は 3 桁か 6 桁しか読めない。6 桁にそろえてから読む。
    読めないと「いつ見たか分からない」扱いになり、生きている端末が消息不明に化ける。
    """
    import re

    s = iso.replace("Z", "+00:00")
    m = re.match(r"^(.*?\.)(\d{1,6})([+-]\d{2}:\d{2}|)$", s)
    if m:
        s = m.group(1) + m.group(2).ljust(6, "0") + m.group(3)
    return s


def _minutes_since(iso: Optional[str], now: datetime) -> Optional[int]:
    if not iso:
        return None
    try:
        seen = datetime.fromisoformat(_normalize_iso(iso))
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
