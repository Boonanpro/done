"""外部宛メッセージ（メール / DM 等）の「文面カード」サービス。

ダンが外部へ送る文面を用意する時の唯一の経路。ダンは `compose_message` ツールで
ここに下書きを作り、チャットに編集可能なカード（`[送信案: <id>]` メッセージ）が出る。
その後は

- ユーザーがカード上で編集（オートセーブ → DB が唯一の正）
- ユーザーが「送信」を押す / ダンが `compose_message(action="send")` を呼ぶ
- 破棄する / 放置する

のどれでもよい。送信・破棄の事実は同じ部屋に `📤` / `🗑` のイベント行として保存され、
次のターンの冒頭ダイジェスト（`digest_for_turn`）でダンの記憶に合流する。
ダンが送る時も本文は渡さず `proposal_id` だけ指定するので、ユーザーの手動編集が
必ず反映される（編集前の文を覚えていても送られるのは DB の現在本文）。

レコードは既存の `dan_proposals` を type="outbound" で使う（DDL 不要）。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 既知チャネルの表示名。channel は自由文字列（chatwork, slack, web_form, x_dm ...）も可。
CHANNELS = {
    "email": "メール",
    "instagram_dm": "Instagram DM",
    "line": "LINE",
    "sms": "SMS",
    "web_form": "Webフォーム",
    "other": "その他",
}


def channel_label(channel: Optional[str]) -> str:
    c = (channel or "other").strip().lower()
    return CHANNELS.get(c, c)


def _reply_subject(subject: Optional[str]) -> Optional[str]:
    if not subject:
        return None
    s = subject.strip()
    return s if s.lower().startswith("re:") else f"Re: {s}"

# サーバー側で実送信できるチャネル。それ以外はダンが browser 等で送って mark_sent する。
SERVER_SENDABLE = {"email"}

CARD_PREFIX = "[送信案: "


def card_marker(proposal_id: str) -> str:
    return f"{CARD_PREFIX}{proposal_id}]"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jst_label(iso: Optional[str] = None) -> str:
    from datetime import timedelta
    try:
        dt = datetime.fromisoformat((iso or _now()).replace("Z", "+00:00"))
    except Exception:
        dt = datetime.now(timezone.utc)
    dt = dt.astimezone(timezone(timedelta(hours=9)))
    return dt.strftime("%m/%d %H:%M")


class OutboundMessageService:
    def __init__(self, supabase=None):
        if supabase is None:
            from app.services.supabase_client import get_supabase_client
            supabase = get_supabase_client().client
        self.sb = supabase

    # ------------------------------------------------------------------
    # 読み取り
    # ------------------------------------------------------------------
    def get(self, proposal_id: str, user_id: Optional[str] = None) -> Optional[dict]:
        q = self.sb.table("dan_proposals").select("*").eq("id", proposal_id).eq("type", "outbound")
        if user_id:
            q = q.eq("user_id", user_id)
        r = q.limit(1).execute()
        return (r.data or [None])[0]

    def list_for_room(self, room_id: str, status: Optional[str] = None, limit: int = 20) -> list[dict]:
        q = (
            self.sb.table("dan_proposals").select("*")
            .eq("type", "outbound").eq("source_room_id", room_id)
            .order("created_at", desc=True).limit(limit)
        )
        if status:
            q = q.eq("status", status)
        return q.execute().data or []

    # ------------------------------------------------------------------
    # 作成（ダンのツールから）
    # ------------------------------------------------------------------
    def create_draft(
        self,
        *,
        user_id: str,
        room_id: str,
        channel: str,
        to: str,
        body: str,
        subject: Optional[str] = None,
        intent: Optional[str] = None,
        to_name: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[dict] = None,
        target: Optional[dict] = None,
    ) -> dict:
        """reply_to: 既存スレッドへの返信なら {message_id, references, subject, detected_message_id}。
        指定時は件名不要（Re: を自動付与し、email は In-Reply-To/References でスレッドに繋ぐ）。
        target: フォーム等の送信先 {url, note}。文面カードはそのまま、送信はダンが browser で行う。"""
        channel = (channel or "other").strip().lower().replace(" ", "_") or "other"
        subject = (subject or "").strip() or None
        # CLI/MCP 経由で "<id@host>" が "&lt;id@host&gt;" に化けて届くことがある（実測 2026-08-28）
        import html as _html
        reply_to = {k: (_html.unescape(v).strip() if isinstance(v, str) else v)
                    for k, v in (reply_to or {}).items() if v} or None
        target = {k: v for k, v in (target or {}).items() if v} or None
        if reply_to and not subject:
            subject = _reply_subject(reply_to.get("subject"))
        if channel == "email" and not subject and not reply_to:
            raise ValueError("email の新規送信には subject が必要です")
        action_data: dict[str, Any] = {
            "action": "outbound_draft",
            "channel": channel,
            "to": to.strip(),
            "to_name": (to_name or "").strip() or None,
            "subject": subject,
            "intent": (intent or "").strip() or None,
            "in_reply_to": in_reply_to,
            "reply_to": reply_to,
            "target": target,
            "from_name": (from_name or "").strip() or None,
            "original_body": body,
            "original_subject": subject,
            "user_edited": False,
            "sent_by": None,
            "sent_at": None,
            # ダイジェスト済みの状態（次ターンで差分だけ知らせるため）
            "ack_status": "pending",
            "ack_body": body,
        }
        title = f"{channel_label(channel)}: {to_name or to}"
        if subject:
            title += f" / {subject}"
        elif reply_to:
            title += " / 返信"
        r = self.sb.table("dan_proposals").insert({
            "user_id": user_id,
            "type": "outbound",
            "status": "pending",
            "title": title[:255],
            "content": body,
            "source_room_id": room_id,
            "action_data": action_data,
        }).execute()
        row = r.data[0]
        self._post_room_message(room_id, card_marker(row["id"]))
        return row

    # ------------------------------------------------------------------
    # 編集（カードのオートセーブ）
    # ------------------------------------------------------------------
    def update_draft(self, proposal_id: str, user_id: str, *, body: Optional[str] = None,
                     subject: Optional[str] = None, to: Optional[str] = None) -> dict:
        row = self.get(proposal_id, user_id)
        if not row:
            raise ValueError("送信案が見つかりません")
        if row["status"] != "pending":
            raise ValueError("この送信案は既に確定しています")
        ad = dict(row.get("action_data") or {})
        upd: dict[str, Any] = {"updated_at": _now()}
        if body is not None:
            upd["content"] = body
            ad["user_edited"] = body != ad.get("original_body")
        if subject is not None:
            ad["subject"] = subject.strip() or None
        if to is not None:
            ad["to"] = to.strip()
        upd["action_data"] = ad
        r = self.sb.table("dan_proposals").update(upd).eq("id", proposal_id).execute()
        return r.data[0]

    # ------------------------------------------------------------------
    # 送信 / 送信済み記録 / 破棄
    # ------------------------------------------------------------------
    async def send(self, proposal_id: str, user_id: str, *, sent_by: str) -> dict:
        """DB の現在本文で実送信する。sent_by = "user" | "dan"。"""
        row = self.get(proposal_id, user_id)
        if not row:
            raise ValueError("送信案が見つかりません")
        if row["status"] != "pending":
            raise ValueError(f"この送信案は既に {row['status']} です（二重送信防止）")
        ad = dict(row.get("action_data") or {})
        channel = ad.get("channel") or "other"
        if channel not in SERVER_SENDABLE:
            raise ValueError(
                f"{channel_label(channel)} はサーバーから直接送信できません。"
                "ダンが browser で送ってから compose_message(action=\"mark_sent\") で記録してください。"
            )
        body = row["content"]
        to = ad.get("to")
        if not to:
            raise ValueError("宛先がありません")

        if channel == "email":
            from app.config import settings
            from app.services.inquiry_notify import _send_smtp, OWNER_REPLY_TO
            reply = ad.get("reply_to") or {}
            subject = ad.get("subject") or _reply_subject(reply.get("subject")) or "(件名なし)"
            from_name = ad.get("from_name") or settings.DAN_DEFAULT_FROM_NAME
            headers = {}
            if reply.get("message_id"):
                headers["In-Reply-To"] = reply["message_id"]
                refs = (reply.get("references") or "").strip()
                headers["References"] = f"{refs} {reply['message_id']}".strip()
            await asyncio.to_thread(
                _send_smtp, to, subject, body, from_name=from_name, reply_to=OWNER_REPLY_TO,
                headers=headers or None,
            )
            try:
                from app.services.external_message_routing import get_external_message_routing_service
                await get_external_message_routing_service().record_outbound(
                    user_id=user_id, channel="gmail", origin_room_id=row["source_room_id"],
                    external_recipient_id=to,
                    external_thread_id=(ad.get("reply_to") or {}).get("message_id"),
                    metadata={"via": "outbound_card", "proposal_id": proposal_id, "sent_by": sent_by,
                              "subject": subject, "reply_to": ad.get("reply_to")},
                )
            except Exception:
                logger.warning("record_outbound failed for %s", proposal_id, exc_info=True)

        return self._finalize_sent(row, ad, sent_by=sent_by)

    def mark_sent(self, proposal_id: str, user_id: str, *, sent_by: str = "dan", note: Optional[str] = None) -> dict:
        """ダンが browser 等で自力送信した後の記録（本文は DB の現在本文）。"""
        row = self.get(proposal_id, user_id)
        if not row:
            raise ValueError("送信案が見つかりません")
        if row["status"] != "pending":
            raise ValueError(f"この送信案は既に {row['status']} です")
        ad = dict(row.get("action_data") or {})
        if note:
            ad["sent_note"] = note
        ad["sent_manually"] = True
        return self._finalize_sent(row, ad, sent_by=sent_by)

    def discard(self, proposal_id: str, user_id: str, *, by: str = "user") -> dict:
        row = self.get(proposal_id, user_id)
        if not row:
            raise ValueError("送信案が見つかりません")
        if row["status"] != "pending":
            raise ValueError(f"この送信案は既に {row['status']} です")
        ad = dict(row.get("action_data") or {})
        ad["discarded_by"] = by
        r = self.sb.table("dan_proposals").update({
            "status": "rejected", "responded_at": _now(), "action_data": ad,
        }).eq("id", proposal_id).execute()
        who = "ユーザー" if by == "user" else "ダン"
        self._post_room_message(
            row["source_room_id"],
            f"🗑 送信案を破棄（{who}・{_jst_label()}）: {row.get('title')}",
        )
        return r.data[0]

    def _finalize_sent(self, row: dict, ad: dict, *, sent_by: str) -> dict:
        now = _now()
        ad["sent_by"] = sent_by
        ad["sent_at"] = now
        ad["final_body"] = row["content"]
        r = self.sb.table("dan_proposals").update({
            "status": "sent", "responded_at": now, "action_data": ad,
        }).eq("id", row["id"]).execute()
        self._post_room_message(row["source_room_id"], self._sent_event_text(row, ad))
        return r.data[0]

    def _sent_event_text(self, row: dict, ad: dict) -> str:
        who = "ユーザーが送信ボタンで送信" if ad.get("sent_by") == "user" else "ダンが送信"
        edited = "・ユーザーが本文を修正" if ad.get("user_edited") else ""
        ch = channel_label(ad.get("channel"))
        head = f"📤 {ch}を送信済み（{who}{edited}・{_jst_label(ad.get('sent_at'))}）\n"
        head += f"宛先: {ad.get('to_name') or ''} {ad.get('to') or ''}".rstrip() + "\n"
        if ad.get("subject"):
            head += f"件名: {ad['subject']}\n"
        return head + "---\n" + (row.get("content") or "")

    # ------------------------------------------------------------------
    # 次ターン用ダイジェスト
    # ------------------------------------------------------------------
    def digest_for_turn(self, room_id: str) -> str:
        """前回ダンが見た状態から変わった送信案（編集・送信・破棄）を文章化し、ack を進める。"""
        try:
            rows = self.list_for_room(room_id, limit=20)
        except Exception:
            return ""
        lines: list[str] = []
        for row in rows:
            ad = dict(row.get("action_data") or {})
            status = row.get("status")
            body = row.get("content") or ""
            if ad.get("ack_status") == status and ad.get("ack_body") == body:
                continue
            label = f"{channel_label(ad.get('channel'))} → {ad.get('to_name') or ad.get('to')}"
            if ad.get("subject"):
                label += f"「{ad['subject']}」"
            if status == "pending":
                lines.append(
                    f"- 送信案 {row['id']}（{label}）: ユーザーが本文を編集した（まだ未送信）。現在の本文:\n{body}"
                )
            elif status == "sent":
                who = "ユーザーが送信ボタンで" if ad.get("sent_by") == "user" else "あなた（ダン）が"
                ed = "本文はユーザーが修正した版。" if ad.get("user_edited") else ""
                lines.append(
                    f"- 送信案 {row['id']}（{label}）: {who}送信済み {_jst_label(ad.get('sent_at'))}。{ed}実際に送った本文:\n{body}"
                )
            elif status == "rejected":
                lines.append(f"- 送信案 {row['id']}（{label}）: 破棄された。")
            ad["ack_status"] = status
            ad["ack_body"] = body
            try:
                self.sb.table("dan_proposals").update({"action_data": ad}).eq("id", row["id"]).execute()
            except Exception:
                logger.warning("ack update failed %s", row["id"], exc_info=True)
        if not lines:
            return ""
        return (
            "【外部宛メッセージ（送信案カード）の更新。あなたが前回見た後に起きたこと】\n"
            + "\n".join(lines)[:6000]
            + "\n【更新ここまで。以下が今回のメッセージ】\n\n"
        )

    # ------------------------------------------------------------------
    def _post_room_message(self, room_id: Optional[str], content: str) -> None:
        if not room_id:
            return
        try:
            from app.services.chat_service import record_message_delivery_sync
            msg_id = str(uuid.uuid4())
            self.sb.table("chat_messages").insert({
                "id": msg_id, "room_id": room_id, "sender_id": None,
                "sender_type": "ai", "content": content,
            }).execute()
            record_message_delivery_sync(self.sb, room_id, msg_id, content=content)
        except Exception:
            logger.warning("post room message failed room=%s", room_id, exc_info=True)


def get_outbound_message_service() -> OutboundMessageService:
    return OutboundMessageService()
