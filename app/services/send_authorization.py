"""ダンが外部へ送る前の関所（2026-11-11 本人と定義した「取り返しのつかない操作」の決まり）。

本人の承認は「その時に見えていた中身」への返事で、後で中身や前提が変わったら使えない。
11/11、本人の「進めて」（台本の作業と文の直しをまとめて頼んだ一言）を送る許可と読み、
台本の直しを本人が見る前に中村さんへ送った。決まりを文で書くだけだとモデルが読み違えるので、
送る道具（compose_message の send と approved=true）の入口でここを必ず通す。

通すのは次のどれか:
- ダンが本人の言葉をそのまま `approval` に写し、それが「この部屋の本人の最新の発言」の中にあり、
  送る・返す・投稿する等の、その操作を名指した言葉を含む。
  さらに、その発言より前からあった下書きを、発言の後に誰かが書き換えていない。
- 本人が前もって任せた予約・定期の送信（「明日9時に送っておいて」「承認不要・報告のみ」）で、その本人の言葉が
  この部屋の見張り（watch）の note に写してあり、approval がそれと同じ。
- 外部窓口（collab）で本人が自動返信を許した（autonomy=auto）窓口への送信。範囲の判断はモデル側。

本人がカードの送信ボタンを押す経路（sent_by="user"）はここを通らない。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, Optional

# その操作を名指した言葉。「進めて」「いいよ」「OK」だけでは通さない（操作を名指していない）。
_EXEC_WORDS = re.compile(
    r"(送って|送っと|送っちゃ|送ってお|送っていい|送ってよ|送って大丈夫|送ってOK|送ってok|送信して|送信お願い|送信で|送ろう|"
    r"送ってください|送っといて|送付して|返信して|返信お願い|返事して|返しといて|返しておいて|返して|"
    r"投稿して|ポストして|公開して|出しといて|出しておいて|"
    r"\bsend\b|\bpost\b)",
    re.IGNORECASE,
)
# 助詞を伴う依頼は本人の文の終わりまで読む。引用・質問の途中を切り出しても依頼にしない。
_REPLY_REQUEST = re.compile(r"(?:返信|返事)を(?:して(?:ください|下さい|おいて)?|お願いします)[。！!]*$")
_STANDING_WORDS = re.compile(r"(承認不要|承認なし|承認無し|確認不要|確認なし|そのまま送|自動で送|報告だけ|報告のみ)")


# 発言全体にこれがあれば通さない（「送って」の部分だけを写して通す読み違いを防ぐ）
_NEG_WORDS = re.compile(
    r"(送らないで|送ってない|送っていない|送るな|送らんで|送っちゃだめ|送ってはだめ|送ってほしくな|送って欲しくな|送らなくて|"
    r"まだ送らな|まだ送るな|送るのは待|送るの待|送信は待|送信を待|ちょっと待って)"
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def check(
    *,
    approval: str,
    latest_owner_message: Optional[Dict[str, Any]],
    watch_notes: list[str],
    proposal: Optional[Dict[str, Any]],
    collab_autonomy: Optional[str] = None,
) -> Dict[str, Any]:
    """{"ok": bool, "reason": str, "basis": str}. 純粋関数（試験しやすいように DB を読まない）。"""
    ad = (proposal or {}).get("action_data") or {}
    if (ad.get("channel") == "collab") and (collab_autonomy or "").lower() == "auto":
        return {"ok": True, "basis": "collab_auto", "reason": "本人が自動返信を許した窓口"}

    quote = _norm(approval)
    if len(quote) < 2:
        return {"ok": False, "basis": "", "reason": (
            "approval に、この送信を許した本人の言葉をそのまま写してください（例:「送って」）。"
            "本人の言葉に送る許可が無いなら送らず、カードのまま本人に送ってよいか聞くこと。")}

    # 前もって任された定期の送信（見張りの note）
    for note in watch_notes or []:
        n = _norm(note)
        if quote in n and (_STANDING_WORDS.search(note or "") or _EXEC_WORDS.search(approval)):
            return {"ok": True, "basis": "watch_note", "reason": "見張りで前もって任された送信"}

    msg_text = (latest_owner_message or {}).get("content") or ""
    if not latest_owner_message or quote not in _norm(msg_text):
        return {"ok": False, "basis": "", "reason": (
            "approval の言葉が、この部屋の本人の最新の発言にありません。承認はその時に見えていた中身にだけ効きます。"
            "前の発言の許可や、他の部屋の許可は使えません。送らずに、今の中身を見せて本人に送ってよいか聞くこと。")}
    if _NEG_WORDS.search(msg_text):
        return {"ok": False, "basis": "", "reason": (
            "本人の最新の発言に、待つ・送らない・止める意味の言葉があります。送らずに、本人に送ってよいか聞くこと。")}
    reply_request = any(
        _REPLY_REQUEST.search(sentence) and sentence in quote
        for sentence in (_norm(part) for part in re.split(r"[。！!\n]+", msg_text))
        if sentence
    )
    if not (_EXEC_WORDS.search(approval) or reply_request):
        return {"ok": False, "basis": "", "reason": (
            f"「{approval.strip()[:40]}」は送ることを名指していません。「進めて」「いいよ」「OK」や、"
            "別の作業と一緒に頼まれた言葉は送る許可に数えません。送らずに、カードのまま本人に送ってよいか聞くこと。")}

    # 本人が承認した後に、承認より前からあった下書きの中身が変わっていないか
    m_at = _ts(latest_owner_message.get("created_at"))
    c_at = _ts((proposal or {}).get("created_at"))
    u_at = _ts((proposal or {}).get("updated_at"))
    if m_at and c_at and u_at and c_at < m_at and u_at > m_at:
        return {"ok": False, "basis": "", "reason": (
            "本人が送ってよいと言った後に、この下書きの中身が変わっています（ダンか本人が書き換えた）。"
            "その承認は使えません。変わった所を短く見せて、改めて送ってよいか聞くこと。")}
    return {"ok": True, "basis": "owner_message", "reason": "本人の最新の発言に送る許可がある"}


def review_prior(approval, proposal, owner, context, later, receipt):
    """Revalidate an identified instruction against the draft visible at the time."""
    denied = {"ok": False, "basis": "", "reason": "この返信案への元の指示、または承認時の条件を照合できません。"}
    references = re.findall(r"\[送信案: ([\w-]+)\]|/message-preview\?proposal=([\w-]+)", context)
    ids = {a or b for a, b in references}
    if ids != {proposal.get("id")} or proposal.get("status") != "pending":
        return denied
    at = _ts(owner.get("created_at"))
    updated = _ts(proposal.get("updated_at"))
    if not at or not updated or updated > at:
        return denied
    # A fragment of a quotation or conditional question cannot be carried forward.
    sentences = [part.strip() for part in re.split(r"[。！!\n]", owner["content"])]
    directive = approval.strip().rstrip("。！!")
    if directive not in sentences or not re.search(
            r"(?:して|送って|送っといて|返して|送付して|出して)(?:ください|下さい|おいて)?$|お願いします$", directive):
        return denied
    original = check(approval=approval, latest_owner_message=owner, proposal=proposal, watch_notes=[])
    if not original["ok"]:
        return original
    for row in later:
        words = row.get("content") or ""
        if row.get("sender_type", "human") == "human" and (
                _NEG_WORDS.search(words) or re.search(r"保留|撤回|取り消|取消|送信中止|送信停止|やめて|やっぱり待", words)):
            return dict(denied, reason="元の指示の後に保留・取り消しの可能性がある発言があります。")
    evidence = [owner, approval, context, proposal, later]
    token = hashlib.sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    if receipt != token:
        return dict(denied, review_token=token, original=owner, context=context, subsequent=later,
                    draft={"body": proposal.get("content"), "delivery": proposal.get("action_data")},
                    reason="元の指示とその後の会話を読み、取り消し・変更・新着連絡・添付や期限の変化を実際の相手先でも確認すること。条件が同じ時だけ review_token を渡してください。")
    return {"ok": True, "basis": "reviewed_owner_message", "reason": "同じ送信案と本人の元の指示を照合しました。"}


def _prior(sb, room_id, user_id, proposal, owner_id, approval, receipt):
    owner = (sb.table("chat_messages").select("id,content,created_at").eq("id", owner_id)
             .eq("room_id", room_id).eq("sender_type", "human").eq("sender_id", user_id).limit(1).execute()).data
    if not owner or not proposal or not proposal.get("id"):
        return {"ok": False, "reason": "本人の元の指示または送信案がありません。"}
    owner = owner[0]
    before = (sb.table("chat_messages").select("content,sender_type,created_at").eq("room_id", room_id)
              .lt("created_at", owner["created_at"]).order("created_at", desc=True).limit(1).execute()).data
    context = ""
    updated = _ts(proposal.get("updated_at"))
    if before and updated and before[0]["sender_type"] == "ai" and _ts(before[0]["created_at"]) >= updated:
        context = before[0]["content"]
    source = proposal["source_room_id"]
    # Older messages linked to the room containing the card, not the card itself.
    linked_rooms = set(re.findall(r"/chat/([\w-]+)", context))
    if linked_rooms == {source}:
        cards = (sb.table("dan_proposals").select("id").eq("source_room_id", source)
                 .eq("type", "outbound").eq("user_id", user_id)
                 .lte("created_at", before[0]["created_at"]).limit(2).execute()).data
        if cards == [{"id": proposal["id"]}]:
            context += "\n[送信案: " + proposal["id"] + "]"
    later = (sb.table("chat_messages").select("id,room_id,sender_type,content,created_at")
             .in_("room_id", sorted({source, room_id})).gt("created_at", owner["created_at"])
             .order("created_at").order("id").limit(101).execute()).data
    if len(later) > 100:
        return {"ok": False, "reason": "承認後の会話が多く、変更の有無を一度に照合できません。"}
    return review_prior(approval, proposal, owner, context, later, receipt)


async def authorize(
    *, approval: str, room_id: str, user_id: str, proposal: Optional[Dict[str, Any]],
    owner_message_id: str = "", review_token: str = "",
) -> Dict[str, Any]:
    """DB から材料を読んで check する。読めない時は通さない（送らない側に倒す）。"""
    import asyncio

    def _load():
        from app.services.supabase_client import get_supabase_client
        from app.services import followups
        sb = get_supabase_client().client
        if owner_message_id:
            return _prior(sb, room_id, user_id, proposal, owner_message_id, approval, review_token)
        rows = (sb.table("chat_messages").select("content,created_at")
                .eq("room_id", room_id).eq("sender_type", "human").eq("sender_id", user_id)
                .order("created_at", desc=True).limit(1).execute()).data or []
        notes = [w.get("plain_note") or "" for w in followups.list_watches(room_id)]
        return (rows[0] if rows else None), notes

    try:
        loaded = await asyncio.to_thread(_load)
        if owner_message_id:
            return loaded
        latest, notes = loaded
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "basis": "", "reason": f"本人の発言を読めず、送る許可を確かめられません（{e}）。送らないこと。"}

    autonomy = None
    ad = (proposal or {}).get("action_data") or {}
    crid = ((ad.get("reply_to") or {}).get("collab_room_id")) or ad.get("collab_room_id")
    if ad.get("channel") == "collab" and crid:
        try:
            from app.services.collab_service import CollabService
            room = await CollabService().get_room(crid)
            autonomy = ((room or {}).get("ai_assist_config") or {}).get("autonomy")
        except Exception:
            autonomy = None
    return check(approval=approval, latest_owner_message=latest, watch_notes=notes,
                 proposal=proposal, collab_autonomy=autonomy)
