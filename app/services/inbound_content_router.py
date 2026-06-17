"""機械照合で確実に当たらなかった受信を、内容判定(LLM)で振り分ける漏れ拾い層。

email_poller が、強い機械一致(STRONG_REASONS)でなかった受信に対して呼ぶ。
ダンが本文を読んで判断する:
  - existing: 既存のどれかのチャットの件 → そのルームに紐づけて返信案(reply)
  - new:      全くの新規の用件        → ルーム非紐づけの返信案(フォームと同じ扱い)
  - ignore:   メルマガ/自動通知/対応不要 → 提案を作らない(inboxに残るだけ)

弱い機械一致(送信者+直近)があっても、内容判定の結論を優先する（別件の取り違え防止）。
判定に失敗したら弱一致にフォールバック、それも無ければ何もしない(無視)。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.external_message_routing import _extract_email, _pick

logger = logging.getLogger(__name__)

_CANDIDATE_LIMIT = 15
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _recent_rooms(sb, limit: int = _CANDIDATE_LIMIT) -> list[dict]:
    rows = (
        sb.table("chat_rooms")
        .select("id,name,last_message_preview,last_message_at")
        .order("last_message_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    return rows


def _parse_json(raw: Optional[str]) -> Optional[dict]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        m = _JSON_RE.search(raw)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _classify(detected_message: dict, rooms: list[dict], weak_room_id: Optional[str]) -> Optional[dict]:
    """run_oneshot_cli で分類。{"decision","room_index","reason"} を返す。"""
    try:
        from app.agent.cli_runner import run_oneshot_cli
    except Exception:
        return None

    sender_info = detected_message.get("sender_info") or {}
    sender = _pick(sender_info.get("from"), sender_info.get("email"), "不明")
    subject = detected_message.get("subject") or "(件名なし)"
    body = (detected_message.get("content") or "")[:2000]

    room_lines = []
    for i, r in enumerate(rooms, 1):
        name = r.get("name") or "(無題)"
        prev = (r.get("last_message_preview") or "").replace("\n", " ")[:60]
        room_lines.append(f"{i}. {name} — {prev}")
    rooms_text = "\n".join(room_lines) if room_lines else "(既存チャットなし)"

    weak_hint = ""
    if weak_room_id:
        for i, r in enumerate(rooms, 1):
            if r.get("id") == weak_room_id:
                weak_hint = f"\n参考: 送信者アドレスだけなら候補{i}が近いが、内容で正しく判断すること。\n"
                break

    prompt = (
        "あなたは運用担当者のアシスタントです。受信メールを読み、下の既存チャット一覧の"
        "どれに関する用件かを判断してください。\n"
        "次のJSONだけを出力（前後に文章を付けない）:\n"
        '{"decision":"existing|new|ignore","room_index":<番号 or null>,"reason":"<短く>"}\n'
        "- existing: 既存チャットのどれかの件への返信/続き → room_index にその番号\n"
        "- new: 既存のどれとも無関係な新規の用件（新規の問い合わせ・営業・依頼など）\n"
        "- ignore: メルマガ・広告・自動通知・領収書など、人間の返信が不要なもの\n"
        f"{weak_hint}\n"
        f"--- 受信メール ---\n差出人: {sender}\n件名: {subject}\n本文:\n{body}\n\n"
        f"--- 既存チャット一覧 ---\n{rooms_text}\n"
    )
    raw = run_oneshot_cli(prompt, "sonnet", 90)
    data = _parse_json(raw)
    if not data or data.get("decision") not in ("existing", "new", "ignore"):
        return None
    return data


async def classify_and_route(
    detected_message: dict[str, Any],
    svc,
    weak_match=None,
) -> Optional[dict[str, Any]]:
    """内容判定して提案を作る。提案を作ったら dict、無視/失敗なら None。"""
    import asyncio

    channel = str(detected_message.get("source") or "").lower()
    if channel not in ("gmail", "email", "icloud"):
        return None  # メール以外は内容判定の対象外（今は）

    sb = svc.supabase
    weak_room_id = weak_match.route["origin_room_id"] if weak_match else None
    rooms = await asyncio.to_thread(_recent_rooms, sb)

    data = await asyncio.to_thread(_classify, detected_message, rooms, weak_room_id)

    if data is None:
        # 判定失敗 → 弱一致があればそれを採用、無ければ何もしない
        if weak_match:
            logger.info("[content-route] LLM判定失敗、弱一致にフォールバック")
            return await svc.apply_match(detected_message, weak_match)
        return None

    decision = data["decision"]
    if decision == "ignore":
        logger.info("[content-route] ignore: %s", data.get("reason"))
        return None

    # 既存ルーム解決
    room_id = None
    if decision == "existing":
        idx = data.get("room_index")
        if isinstance(idx, int) and 1 <= idx <= len(rooms):
            room_id = rooms[idx - 1]["id"]
        elif weak_room_id:
            room_id = weak_room_id
        else:
            decision = "new"  # 番号不正なら新規扱い

    # 返信草案を生成
    sender_info = detected_message.get("sender_info") or {}
    sender = _pick(sender_info.get("from"), sender_info.get("email"), "不明")
    sender_email = _extract_email(sender) or _pick(sender_info.get("email"))
    subject = detected_message.get("subject") or "(件名なし)"
    body = detected_message.get("content") or ""
    draft = await svc._draft_email_reply(sender, subject, body)

    if not sender_email or not draft:
        logger.info("[content-route] 返信先メール無し or 草案失敗 → 通知のみ")
        title = "新規メール（要対応）" if decision == "new" else "メール（要対応）"
        content = f"差出人: {sender}\n件名: {subject}\n\n{body[:1200]}"
        action_data = {"action": "inbound_email_no_reply", "detected_message_id": detected_message["id"]}
        ptype = "action"
    else:
        reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        title = (f"新規メール返信案: {sender}" if decision == "new" else f"メール返信案: {sender}")
        content = draft
        action_data = {
            "action": "send_email_reply",
            "channel": "email",
            "to": sender_email,
            "subject": reply_subject,
            "detected_message_id": detected_message["id"],
            "routing_reason": f"content:{decision}",
        }
        ptype = "reply"

    def _insert():
        row = {
            "user_id": detected_message["user_id"],
            "type": ptype,
            "title": title,
            "content": content,
            "status": "pending",
            "action_data": action_data,
        }
        if room_id:
            row["source_room_id"] = room_id
        return sb.table("dan_proposals").insert(row).execute()

    result = await asyncio.to_thread(_insert)
    proposal = result.data[0] if result.data else None

    # detected_messages を routed として印付け（再処理防止）
    now = datetime.now(timezone.utc).isoformat()
    pr = {**(detected_message.get("processing_result") or {}),
          "routing_attempted": True,
          "content_decision": decision,
          "content_reason": data.get("reason")}
    upd = {"processing_result": pr, "routed_at": now}
    if room_id:
        upd["routed_room_id"] = room_id
        upd["routing_reason"] = f"content:{decision}"

    def _mark():
        return sb.table("detected_messages").update(upd).eq("id", detected_message["id"]).execute()

    await asyncio.to_thread(_mark)
    logger.info("[content-route] decision=%s room=%s proposal=%s", decision, room_id, bool(proposal))
    return {"decision": decision, "room_id": room_id, "proposal": proposal}
