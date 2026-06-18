"""着信(detect_message経由)を dan-notion の案件×サブフォルダへ内容判定で自動仕分けする。

全チャネル共通の取込層に置く想定の共有関数。メールで作り、SNS/ダンチャットが
detect_message に流れ込めば同じロジックで横展開される。

方針(ユーザー決定):
  - 自動仕分け＋不明はinboxに残して提案
  - 該当案件が無ければ新規案件(client_root)を自動作成
仕分け先サブフォルダ: 資料(契約書/書類PDF) / 動画素材 / 画像素材 / 制作物。
添付の無い純粋なお知らせ/メルマガは無理に案件化せず inbox に残す。
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

_FOLDER_KINDS = {"folder_document", "folder_video", "folder_image", "folder_production"}
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


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


def _find_inbox_message_block(sb, user_id: str, source: str, source_id: Optional[str], detected_id: str):
    guard = source_id or detected_id
    rows = (
        sb.table("blocks").select("id,parent_id,properties")
        .eq("user_id", user_id).eq("source", source).eq("source_id", str(guard))
        .is_("deleted_at", "null").limit(3).execute().data or []
    )
    for b in rows:
        if (b.get("properties") or {}).get("kind") == "message":
            return b
    return None


def _list_clients(sb, user_id: str) -> list[dict]:
    """既存 client_root 一覧 [(id, client_id, title)]。"""
    rows = (
        sb.table("blocks").select("id,properties,source_id")
        .eq("user_id", user_id).eq("source", "agent").is_("deleted_at", "null")
        .limit(500).execute().data or []
    )
    out = []
    for b in rows:
        pr = b.get("properties") or {}
        if pr.get("kind") == "client_root":
            out.append({"id": b["id"], "client_id": pr.get("client_id") or b.get("source_id"),
                        "title": pr.get("title") or "(無題)"})
    return out


def _classify(detected_message: dict, clients: list[dict]) -> Optional[dict]:
    try:
        from app.agent.cli_runner import run_oneshot_cli
    except Exception:
        return None
    si = detected_message.get("sender_info") or {}
    sender = si.get("from") or si.get("email") or "不明"
    subject = detected_message.get("subject") or "(件名なし)"
    body = (detected_message.get("content") or "")[:1500]
    atts = (detected_message.get("metadata") or {}).get("attachments") or []
    att_text = "\n".join(f"- {a.get('filename')} ({a.get('content_type')})" for a in atts) or "(添付なし)"
    client_lines = "\n".join(f"{i}. {c['title']}" for i, c in enumerate(clients, 1)) or "(既存案件なし)"

    prompt = (
        "あなたは運用者のアシスタントです。受信物を案件ごとに整理します。\n"
        "次のJSONだけ出力（前後に文を付けない）:\n"
        '{"decision":"existing|new|inbox","client_index":<番号 or null>,"new_client_name":"<新規時の案件名 or null>",'
        '"folder_kind":"folder_document|folder_video|folder_image|folder_production|none","reason":"<短く>"}\n'
        "- existing: 既存案件のどれか → client_index にその番号\n"
        "- new: 既存に無い新しい取引先/案件 → new_client_name に簡潔な案件名(会社名や人名)\n"
        "- inbox: 案件として整理すべきか不明、または宣伝/メルマガ等で整理不要 → そのまま\n"
        "folder_kind: 契約書/見積/請求書/書類PDF=folder_document, 動画=folder_video, 画像=folder_image, "
        "完成した制作物=folder_production, 本文だけ/判断つかない=none\n\n"
        f"--- 受信 ---\n差出人: {sender}\n件名: {subject}\n添付:\n{att_text}\n本文:\n{body}\n\n"
        f"--- 既存案件一覧 ---\n{client_lines}\n"
    )
    return _parse_json(run_oneshot_cli(prompt, "sonnet", 90))


async def sort_detected_message(detected_message: dict[str, Any]) -> Optional[dict[str, Any]]:
    """検知メッセージを dan-notion の案件×フォルダへ仕分ける。

    Returns: {"decision","client","folder_kind"} 等 / None(対象外)。
    """
    import asyncio

    from app.services.dan_notion_service import get_dan_notion_service
    from app.services.supabase_client import get_supabase_client

    user_id = detected_message.get("user_id")
    source = (detected_message.get("source") or "").lower()
    if not user_id or not source:
        return None

    sb = get_supabase_client().client
    svc = get_dan_notion_service()

    # inbox にある該当メッセージ block（無ければ仕分け対象外）
    block = await asyncio.to_thread(
        _find_inbox_message_block, sb, user_id, source,
        detected_message.get("source_id"), detected_message["id"],
    )
    if not block:
        return None

    clients = await asyncio.to_thread(_list_clients, sb, user_id)
    data = await asyncio.to_thread(_classify, detected_message, clients)
    if not data or data.get("decision") not in ("existing", "new", "inbox"):
        return None

    decision = data["decision"]
    if decision == "inbox":
        logger.info("[notion-sort] inbox(据置): %s", data.get("reason"))
        # 不明 → inbox に残し、要確認の通知を出す
        await asyncio.to_thread(_notify_unsorted, sb, detected_message, data.get("reason"))
        return {"decision": "inbox"}

    def _resolve_and_move():
        # 案件 root を解決 or 作成
        if decision == "existing":
            idx = data.get("client_index")
            if not (isinstance(idx, int) and 1 <= idx <= len(clients)):
                return None
            client = clients[idx - 1]
            root = sb.table("blocks").select("*").eq("id", client["id"]).execute().data[0]
            client_id = client["client_id"]
        else:  # new
            name = (data.get("new_client_name") or "").strip() or (detected_message.get("subject") or "新規案件")
            client_id = f"inbound-{uuid.uuid4().hex[:10]}"
            root = svc.get_or_create_client_root(user_id, client_id, name[:60])

        folder_kind = data.get("folder_kind")
        if folder_kind in _FOLDER_KINDS:
            target = svc.get_or_create_subfolder(user_id, root["id"], client_id, folder_kind)
        else:
            target = root  # 本文のみ等は案件直下

        target_id = target["id"]
        order_key = svc._compute_order_key(user_id, target_id, after_block_id=None)
        sb.table("blocks").update({"parent_id": target_id, "order_key": order_key}).eq("id", block["id"]).execute()
        return {"client_title": root.get("properties", {}).get("title"), "folder_kind": folder_kind}

    moved = await asyncio.to_thread(_resolve_and_move)
    logger.info("[notion-sort] decision=%s moved=%s", decision, moved)
    return {"decision": decision, **(moved or {})}


def _notify_unsorted(sb, detected_message: dict, reason: Optional[str]):
    """案件不明の着信を「どの案件に整理しますか？」として通知タブに出す。"""
    si = detected_message.get("sender_info") or {}
    sender = si.get("from") or si.get("email") or "不明"
    subject = detected_message.get("subject") or "(件名なし)"
    sb.table("dan_proposals").insert({
        "user_id": detected_message["user_id"],
        "type": "notify",
        "title": "確認してください",
        "content": f"{sender} から「{subject}」が届きましたが、どの案件に整理すべきか判断できませんでした。"
                   f"dan-notion の inbox に保留しています。",
        "status": "pending",
        "action_data": {
            "action": "notion_unsorted",
            "summary": f"{sender} から「{subject}」。案件不明のため inbox 保留（{reason or '判断不可'}）。",
            "from_sender": sender,
            "detected_message_id": detected_message["id"],
        },
    }).execute()
