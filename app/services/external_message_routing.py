from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

ROUTING_KEY_RE = re.compile(r"\b(?:DK|MSG|OUT|REF)-[A-Z0-9][A-Z0-9_-]{5,40}\b", re.IGNORECASE)


def _norm(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _pick(*values: Any) -> Optional[str]:
    for value in values:
        normalized = _norm(value)
        if normalized:
            return normalized
    return None


def _dig(data: dict[str, Any], *keys: str) -> Optional[str]:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return _norm(cur)


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _extract_email(value: Optional[str]) -> Optional[str]:
    """'名前 <a@b.com>' や 'a@b.com' から最初のメールアドレスを抜く。"""
    if not value:
        return None
    m = _EMAIL_RE.search(value)
    return m.group(0) if m else None


def _split_summary_reply(raw: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """run_oneshot_cli 出力を (概要, 返信本文) に分解する。

    期待形式: 【概要】... 【返信案】... 。マーカーが無ければ全体を返信本文扱い。
    """
    if not raw:
        return None, None
    text = raw.strip()
    if "【返信案】" in text:
        head, _, body = text.partition("【返信案】")
        summary = head.replace("【概要】", "").strip()
        return (summary or None), (body.strip() or None)
    return None, (text or None)


def _split_summary_reply_schedule(raw: Optional[str]):
    """run_oneshot_cli 出力を (概要, 返信本文, 予定dict|None) に分解する。

    形式: 【概要】... 【返信案】... 【予定】(JSON or なし)
    """
    if not raw:
        return None, None, None
    text = raw.strip()
    schedule = None
    main = text
    if "【予定】" in text:
        main, _, sched_part = text.partition("【予定】")
        sched_part = sched_part.strip()
        if sched_part and "なし" not in sched_part[:6] and "null" not in sched_part[:6].lower():
            m = re.search(r"\{.*\}", sched_part, re.DOTALL)
            if m:
                try:
                    schedule = json.loads(m.group(0))
                except Exception:
                    schedule = None
    summary, reply = _split_summary_reply(main)
    return summary, reply, schedule


def _with_signature(reply: Optional[str]) -> Optional[str]:
    """返信本文の末尾にパイナ署名ブロックを付与する。reply が空なら None のまま。"""
    if not reply:
        return reply
    try:
        from app.config import settings
        sig = settings.DAN_EMAIL_SIGNATURE
    except Exception:
        return reply
    body = reply.rstrip()
    if sig and sig.strip() and sig.strip() not in body:
        return f"{body}\n\n{sig}"
    return body


def _first_routing_key(*texts: Optional[str]) -> Optional[str]:
    for text in texts:
        if not text:
            continue
        match = ROUTING_KEY_RE.search(text)
        if match:
            return match.group(0).upper()
    return None


# 「確実」とみなす照合理由（ヘッダ/合言葉=事実）。これらは内容判定を挟まず即確定。
# 送信者アドレス+直近(external_recipient_id_recent)は弱いので内容判定でダブルチェックする。
STRONG_REASONS = frozenset({"external_thread_id", "in_reply_to_message_id", "routing_key"})


@dataclass(frozen=True)
class RouteMatch:
    route: dict[str, Any]
    confidence: float
    reason: str


class ExternalMessageRoutingService:
    """Maps external replies back to the chat room that initiated outreach."""

    def __init__(self) -> None:
        self.supabase = get_supabase_client().client

    async def record_outbound(
        self,
        *,
        user_id: str,
        channel: str,
        origin_room_id: str,
        origin_message_id: Optional[str] = None,
        external_account_id: Optional[str] = None,
        external_recipient_id: Optional[str] = None,
        external_thread_id: Optional[str] = None,
        external_message_id: Optional[str] = None,
        routing_key: Optional[str] = None,
        campaign_id: Optional[str] = None,
        contact_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Register a sent external message as a routing target for replies."""
        row = {
            "user_id": user_id,
            "channel": channel.lower(),
            "origin_room_id": origin_room_id,
            "origin_message_id": origin_message_id,
            "external_account_id": external_account_id,
            "external_recipient_id": external_recipient_id,
            "external_thread_id": external_thread_id,
            "external_message_id": external_message_id,
            "routing_key": routing_key.upper() if routing_key else None,
            "campaign_id": campaign_id,
            "contact_id": contact_id,
            "metadata": metadata or {},
            "last_outbound_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        result = self.supabase.table("external_message_routes").insert(row).execute()
        if not result.data:
            raise ValueError("Failed to record outbound message route")
        return result.data[0]

    async def route_detected_message(self, detected_message: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Route a detected inbound message and create a Dan action proposal.

        機械照合(find_route)で一致したものを適用する。強弱の判定や内容判定の
        フォールバックは呼び出し側(email_poller)が STRONG_REASONS / apply_match で行う。
        """
        match = self.find_route(detected_message)
        if not match:
            return None
        return await self.apply_match(detected_message, match)

    async def apply_match(self, detected_message: dict[str, Any], match: RouteMatch) -> dict[str, Any]:
        """確定した RouteMatch を detected_messages に反映し、返信案/通知の提案を作る。"""
        detected_id = detected_message["id"]
        room_id = match.route["origin_room_id"]
        now = datetime.now(timezone.utc).isoformat()

        self.supabase.table("detected_messages").update({
            "routed_room_id": room_id,
            "routing_confidence": match.confidence,
            "routing_reason": match.reason,
            "routed_at": now,
            "processing_result": {
                **(detected_message.get("processing_result") or {}),
                "external_route_id": match.route["id"],
                "origin_room_id": room_id,
                "routing_reason": match.reason,
                "routing_confidence": match.confidence,
            },
        }).eq("id", detected_id).execute()

        proposal = await self._create_proposal(detected_message, match)
        logger.info(
            "Routed detected message %s to room %s via %s",
            detected_id,
            room_id,
            match.reason,
        )
        return {
            "route": match.route,
            "confidence": match.confidence,
            "reason": match.reason,
            "proposal": proposal,
        }

    def find_route(self, detected_message: dict[str, Any]) -> Optional[RouteMatch]:
        user_id = detected_message.get("user_id")
        channel = str(detected_message.get("source") or "").lower()
        if not user_id or not channel:
            return None

        metadata = detected_message.get("metadata") or {}
        sender_info = detected_message.get("sender_info") or {}
        content = detected_message.get("content") or ""
        subject = detected_message.get("subject") or ""

        thread_id = _pick(
            metadata.get("external_thread_id"),
            metadata.get("thread_id"),
            metadata.get("conversation_id"),
            metadata.get("gmail_thread_id"),
            sender_info.get("thread_id"),
            sender_info.get("conversation_id"),
        )
        message_ref = _pick(
            metadata.get("in_reply_to_message_id"),
            metadata.get("in_reply_to"),
            metadata.get("reply_to_message_id"),
            metadata.get("references"),
            sender_info.get("in_reply_to"),
        )
        routing_key = _pick(
            metadata.get("routing_key"),
            sender_info.get("routing_key"),
            _first_routing_key(subject, content),
        )
        recipient_id = _pick(
            metadata.get("external_sender_id"),
            metadata.get("sender_id"),
            sender_info.get("external_sender_id"),
            sender_info.get("sender_id"),
            sender_info.get("from"),
            sender_info.get("email"),
            _dig(sender_info, "from", "email"),
        )

        if thread_id:
            route = self._latest_route(user_id, channel, "external_thread_id", thread_id)
            if route:
                return RouteMatch(route=route, confidence=1.0, reason="external_thread_id")

        if message_ref:
            route = self._latest_route(user_id, channel, "external_message_id", message_ref)
            if route:
                return RouteMatch(route=route, confidence=0.98, reason="in_reply_to_message_id")

        if routing_key:
            route = self._latest_route(user_id, channel, "routing_key", routing_key.upper())
            if route:
                return RouteMatch(route=route, confidence=0.95, reason="routing_key")

        if recipient_id:
            route = self._latest_route(user_id, channel, "external_recipient_id", recipient_id)
            if route:
                return RouteMatch(route=route, confidence=0.7, reason="external_recipient_id_recent")

        return None

    def _latest_route(self, user_id: str, channel: str, field: str, value: str) -> Optional[dict[str, Any]]:
        result = (
            self.supabase.table("external_message_routes")
            .select("*")
            .eq("user_id", user_id)
            .eq("channel", channel)
            .eq(field, value)
            .order("last_outbound_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    async def _create_proposal(self, detected_message: dict[str, Any], match: RouteMatch) -> Optional[dict[str, Any]]:
        channel = str(detected_message.get("source") or "")
        sender_info = detected_message.get("sender_info") or {}
        sender = _pick(sender_info.get("from"), sender_info.get("sender_name"), sender_info.get("email"), "不明")
        sender_email = _extract_email(sender) or _pick(sender_info.get("email"))
        subject = detected_message.get("subject") or "(件名なし)"
        body = (detected_message.get("content") or "").strip()
        body_trunc = body[:1200] + "\n..." if len(body) > 1200 else body

        # メール返信なら、ダンが返信草案を作って「要対応の返信案(reply)」として提案する。
        # 承認すると chat_service._execute_reply_proposal が SMTP で送信する。
        if channel in ("gmail", "email", "icloud") and sender_email:
            summary, draft = await self._draft_email_reply(sender, subject, body, detected_message.get("user_id"))
            if draft:
                reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
                result = self.supabase.table("dan_proposals").insert({
                    "user_id": detected_message["user_id"],
                    "type": "reply",
                    "title": "返信しますか？",
                    "content": draft,
                    "source_room_id": match.route["origin_room_id"],
                    "source_message_id": match.route.get("origin_message_id"),
                    "status": "pending",
                    "action_data": {
                        "action": "send_email_reply",
                        "channel": "email",
                        "to": sender_email,
                        "subject": reply_subject,
                        "summary": summary,
                        "from_sender": sender,
                        "original_body": body[:2000],
                        "detected_message_id": detected_message["id"],
                        "external_route_id": match.route["id"],
                        "routing_reason": match.reason,
                        "routing_confidence": match.confidence,
                    },
                }).execute()
                return result.data[0] if result.data else None

        # それ以外（草案不可・非メール）は従来の通知(action)
        content = (
            f"外部チャネル `{channel}` で返信を検知し、このチャットに振り分けました。\n\n"
            f"送信者: {sender}\n"
            f"件名: {subject}\n"
            f"振り分け理由: {match.reason} / confidence={match.confidence:.2f}\n\n"
            f"--- 返信本文 ---\n{body_trunc}"
        )
        result = self.supabase.table("dan_proposals").insert({
            "user_id": detected_message["user_id"],
            "type": "action",
            "title": "確認してください",
            "content": content,
            "source_room_id": match.route["origin_room_id"],
            "source_message_id": match.route.get("origin_message_id"),
            "status": "pending",
            "action_data": {
                "action": "external_reply_detected",
                "detected_message_id": detected_message["id"],
                "external_route_id": match.route["id"],
                "channel": channel,
                "routing_reason": match.reason,
                "routing_confidence": match.confidence,
            },
        }).execute()
        return result.data[0] if result.data else None

    async def _draft_email_reply(
        self, sender: str, subject: str, body: str, user_id: Optional[str] = None
    ) -> tuple[Optional[str], Optional[str]]:
        """受信メールの「自然な概要」と「返信本文」を run_oneshot_cli で生成する。

        カレンダー連携:
          - 返信で日程提案するなら、運用者の空き時間を渡し空いている時間だけ提案させる。
          - 受信メールで日時が確定していれば、その予定を抽出してカレンダーに登録し
            （重複は登録しない）、概要に「📅 登録しました」と添える。

        Returns: (summary, reply)。失敗時 (None, None)。
        """
        import asyncio as _asyncio
        try:
            from app.agent.cli_runner import run_oneshot_cli
            from app.config import settings
            from_name = settings.DAN_DEFAULT_FROM_NAME
        except Exception:
            return None, None

        if not user_id:
            try:
                from app.services.owner import resolve_owner_user_id
                user_id = resolve_owner_user_id()
            except Exception:
                user_id = None

        # 空き時間を取得（カレンダー未連携なら空文字で続行）
        free_text = "(カレンダー未連携)"
        try:
            from app.services.calendar_service import get_calendar_service
            cal = get_calendar_service()
            slots = await _asyncio.to_thread(cal.find_free_slots, user_id, 10)
            if slots and not (isinstance(slots[0], dict) and slots[0].get("error")):
                free_text = "\n".join(f"- {s['date']} {s['start']}〜{s['end']}" for s in slots[:25])
        except Exception:
            cal = None

        prompt = (
            f"あなたは「{from_name}」の担当者として、以下の受信メールに返信します。\n"
            "次の3つを作り、形式を厳守してください（他の文字を足さない）:\n"
            "【概要】<1〜2文の自然な日本語。誰から何の件で何を求めているか>\n"
            "【返信案】\n<丁寧で簡潔な返信本文のみ。署名・会社名・連絡先は書かない（自動付与）>\n"
            "【予定】<相手と日時が『確定』した場合のみJSON {\"title\":\"...\",\"start\":\"YYYY-MM-DDTHH:MM:00\",\"end\":\"...\"} を出す。"
            "単に候補を提示・打診しているだけ、未確定、日時が無い場合は「なし」と書く。創作しない>\n\n"
            "重要:\n"
            "- 本文に無い日時・約束・事実を創作しない。\n"
            "- こちらから日程を提案する場合は、下記『空き時間』の中からのみ提案する（埋まっている時間は出さない）。\n\n"
            f"--- 運用者の空き時間(今後10日, 9-18時) ---\n{free_text}\n\n"
            f"--- 受信メール ---\n差出人: {sender}\n件名: {subject}\n本文:\n{body[:2000]}\n"
        )
        try:
            raw = await _asyncio.to_thread(run_oneshot_cli, prompt, "sonnet", 90)
        except Exception:
            return None, None

        summary, reply, schedule = _split_summary_reply_schedule(raw)
        reply = _with_signature(reply)

        # 確定予定があればカレンダー登録（重複は避ける）
        if schedule and schedule.get("start") and user_id:
            try:
                note = await _asyncio.to_thread(
                    self._register_calendar_event, user_id, sender, subject, schedule
                )
                if note and summary:
                    summary = f"{summary}\n{note}"
                elif note:
                    summary = note
            except Exception:
                logger.exception("calendar register failed")

        return summary, reply

    def _register_calendar_event(self, user_id: str, sender: str, subject: str, schedule: dict) -> Optional[str]:
        """確定予定をカレンダー登録。同時間帯に既存予定があれば登録せず注記のみ。"""
        from app.services.calendar_service import get_calendar_service
        cal = get_calendar_service()
        start = schedule.get("start")
        end = schedule.get("end") or start
        title = schedule.get("title") or f"{_extract_email(sender) or sender} 打ち合わせ"

        # 重複チェック: 同日の既存予定と開始時刻が一致/近接なら登録しない
        try:
            events = cal.get_events(user_id, days=30, max_results=50)
            for ev in events or []:
                if isinstance(ev, dict) and ev.get("start") and str(ev["start"])[:16] == str(start)[:16]:
                    return f"📅 既にカレンダーに同時刻の予定あり（{start}）"
        except Exception:
            pass

        r = cal.create_event(user_id, title=title, start=start, end=end, description=f"自動登録: {subject}")
        if r and not r.get("error"):
            return f"📅 カレンダーに登録しました（{start} {title}）"
        return None


_routing_service: Optional[ExternalMessageRoutingService] = None


def get_external_message_routing_service() -> ExternalMessageRoutingService:
    global _routing_service
    if _routing_service is None:
        _routing_service = ExternalMessageRoutingService()
    return _routing_service

