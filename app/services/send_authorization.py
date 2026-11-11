"""ダンが外部へ送る前の関所（2026-11-11 本人と定義した「取り返しのつかない操作」の決まり）。

本人の承認は「その時に見えていた中身」への返事で、後で中身や前提が変わったら使えない。
11/11、本人の「進めて」（台本の作業と文の直しをまとめて頼んだ一言）を送る許可と読み、
台本の直しを本人が見る前に中村さんへ送った。決まりを文で書くだけだとモデルが読み違えるので、
送る道具（compose_message の send と approved=true）の入口でここを必ず通す。

通すのは次のどれか:
- ダンが本人の言葉をそのまま `approval` に写し、それが「この部屋の本人の最新の発言」の中にあり、
  送る・返す・投稿する等の、その操作を名指した言葉を含む。
  さらに、その発言より前からあった下書きを、発言の後に誰かが書き換えていない。
- 本人が見張り（watch）の note に「承認不要」等で前もって任せた定期の送信で、approval がその note にある。
- 外部窓口（collab）で本人が自動返信を許した（autonomy=auto）窓口への送信。範囲の判断はモデル側。

本人がカードの送信ボタンを押す経路（sent_by="user"）はここを通らない。
"""
from __future__ import annotations

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
        if quote in n and _STANDING_WORDS.search(note or ""):
            return {"ok": True, "basis": "watch_note", "reason": "見張りで前もって任された送信"}

    msg_text = (latest_owner_message or {}).get("content") or ""
    if not latest_owner_message or quote not in _norm(msg_text):
        return {"ok": False, "basis": "", "reason": (
            "approval の言葉が、この部屋の本人の最新の発言にありません。承認はその時に見えていた中身にだけ効きます。"
            "前の発言の許可や、他の部屋の許可は使えません。送らずに、今の中身を見せて本人に送ってよいか聞くこと。")}
    if _NEG_WORDS.search(msg_text):
        return {"ok": False, "basis": "", "reason": (
            "本人の最新の発言に、待つ・送らない・止める意味の言葉があります。送らずに、本人に送ってよいか聞くこと。")}
    if not _EXEC_WORDS.search(approval):
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


async def authorize(
    *, approval: str, room_id: str, user_id: str, proposal: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """DB から材料を読んで check する。読めない時は通さない（送らない側に倒す）。"""
    import asyncio

    def _load():
        from app.services.supabase_client import get_supabase_client
        from app.services import followups
        sb = get_supabase_client().client
        rows = (sb.table("chat_messages").select("content,created_at")
                .eq("room_id", room_id).eq("sender_type", "human")
                .order("created_at", desc=True).limit(1).execute()).data or []
        notes = [w.get("plain_note") or "" for w in followups.list_watches(room_id)]
        return (rows[0] if rows else None), notes

    try:
        latest, notes = await asyncio.to_thread(_load)
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
