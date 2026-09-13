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
    "instagram_comment": "Instagramコメント",
    "web_form": "Webフォーム",
    "collab": "コラボチャット",
    "other": "その他",
}

# 表記揺れの正規化
_CHANNEL_ALIASES = {"instagram": "instagram_dm", "ig": "instagram_dm", "ig_dm": "instagram_dm",
                    "insta": "instagram_dm", "ig_comment": "instagram_comment",
                    "mail": "email", "gmail": "email", "form": "web_form", "webform": "web_form",
                    "collab_chat": "collab", "collab_room": "collab"}


def channel_label(channel: Optional[str]) -> str:
    c = (channel or "other").strip().lower()
    return CHANNELS.get(c, c)


def _reply_subject(subject: Optional[str]) -> Optional[str]:
    if not subject:
        return None
    s = subject.strip()
    return s if s.lower().startswith("re:") else f"Re: {s}"

# サーバー側で実送信できるチャネル。それ以外はダンが browser 等で送って mark_sent する。
# instagram_* は巡回用プロファイル（ログイン済み）から内部APIで送る（instagram_send）。
# collab は自前DB（collab_messages）＋sandbox の WS/Push 配信なので最も確実。
SERVER_SENDABLE = {"email", "instagram_dm", "instagram_comment", "collab"}

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
        from_account: Optional[str] = None,
        attachments: Optional[list] = None,
        sender: Optional[str] = None,
    ) -> dict:
        """reply_to: 既存スレッドへの返信なら {message_id, references, subject, detected_message_id}。
        attachments: 相手へ一緒に届ける画像・動画・ファイル（ローカルパス or URL）。collab のみ。
        sender: "dan"（既定）| "owner" — どちらの名義で相手に届くか。collab のみ。
        指定時は件名不要（Re: を自動付与し、email は In-Reply-To/References でスレッドに繋ぐ）。
        target: フォーム等の送信先 {url, note}。文面カードはそのまま、送信はダンが browser で行う。"""
        channel = (channel or "other").strip().lower().replace(" ", "_") or "other"
        channel = _CHANNEL_ALIASES.get(channel, channel)
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

        collab_room_id = (reply_to or {}).get("collab_room_id") or (target or {}).get("collab_room_id")
        staged_files = self._stage_collab_attachments(collab_room_id, attachments) if (channel == "collab" and attachments) else []
        sender = (sender or "").strip().lower() or "dan"
        if sender not in ("dan", "owner"):
            sender = "dan"

        # 1窓口=1下書き: 同じ窓口に未送信の下書きがあれば、新しいカードを作らず育てる。
        # 作業が進むたびにカードが増えて古い文面が残る事故（2026-09-12）の根本対策。
        # ユーザーが本文を手で直している時だけは上書きせず、新版を「更新あり」として横に置く。
        if channel == "collab" and collab_room_id:
            existing = self._find_pending_collab_draft(user_id, collab_room_id)
            if existing:
                return self._revise_collab_draft(existing, body=body, intent=intent, to_name=to_name,
                                                 files=staged_files, sender=sender if sender != "dan" else None)

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
            "from_account": (from_account or (reply_to or {}).get("account") or "").strip().lstrip("@") or None,
            "from_name": (from_name or "").strip() or None,
            "original_body": body,
            "original_subject": subject,
            # collab: 相手へ一緒に届ける添付（propose 時点で窓口の保存先へ写してある）
            "attachments": staged_files or None,
            # collab: 名義。"dan"=ダンとして届く / "owner"=ユーザー本人として届く（カードで切替可）
            "sender": sender if channel == "collab" else None,
            "revision": 1,
            "dan_updated_at": _now(),
            "pending_update": None,
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
        # collab（外部窓口）のカードはコミュニケーションタブ側に表示されるため、
        # 本体チャットにはカード行を出さない（ダンの記憶は digest_for_turn が届ける）。
        if channel != "collab":
            self._post_room_message(room_id, card_marker(row["id"]))
        return row

    # ------------------------------------------------------------------
    # 編集（カードのオートセーブ）
    # ------------------------------------------------------------------
    def update_draft(self, proposal_id: str, user_id: str, *, body: Optional[str] = None,
                     subject: Optional[str] = None, to: Optional[str] = None,
                     sender: Optional[str] = None, apply_update: bool = False) -> dict:
        row = self.get(proposal_id, user_id)
        if not row:
            raise ValueError("送信案が見つかりません")
        if row["status"] == "sending":
            raise ValueError("送信中（ダンが送信作業中）のため編集できません")
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
        if sender in ("dan", "owner"):
            ad["sender"] = sender
        if apply_update and ad.get("pending_update"):
            # ダンが用意した新版を採用（ユーザー編集を捨てて置き換える。明示操作のみ）
            pu = ad.pop("pending_update") or {}
            upd["content"] = pu.get("body") or row["content"]
            ad["original_body"] = upd["content"]
            ad["ack_body"] = upd["content"]
            ad["user_edited"] = False
            if pu.get("intent"):
                ad["intent"] = pu["intent"]
            if pu.get("attachments") is not None:
                ad["attachments"] = pu["attachments"]
            ad["revision"] = int(ad.get("revision") or 1) + 1
            ad["pending_update"] = None
        upd["action_data"] = ad
        r = self.sb.table("dan_proposals").update(upd).eq("id", proposal_id).execute()
        return r.data[0]

    # ------------------------------------------------------------------
    # collab: 1窓口=1下書き のための補助
    # ------------------------------------------------------------------
    def _find_pending_collab_draft(self, user_id: str, collab_room_id: str) -> Optional[dict]:
        try:
            r = (self.sb.table("dan_proposals").select("*")
                 .eq("user_id", user_id).eq("type", "outbound").eq("status", "pending")
                 .order("created_at", desc=True).limit(30).execute())
        except Exception:
            return None
        for row in r.data or []:
            ad = row.get("action_data") or {}
            if ad.get("channel") != "collab":
                continue
            cid = (ad.get("reply_to") or {}).get("collab_room_id") or (ad.get("target") or {}).get("collab_room_id")
            if cid == collab_room_id:
                return row
        return None

    def _revise_collab_draft(self, row: dict, *, body: str, intent: Optional[str], to_name: Optional[str],
                             files: list, sender: Optional[str]) -> dict:
        ad = dict(row.get("action_data") or {})
        now = _now()
        upd: dict[str, Any] = {"updated_at": now}
        new_files = files if files else (ad.get("attachments") or None)
        if ad.get("user_edited"):
            # ユーザーが手で直している最中。上書きせず新版を横に置く（カードに「更新あり」）
            ad["pending_update"] = {"body": body, "intent": (intent or "").strip() or None,
                                    "attachments": new_files, "at": now}
            ad["dan_updated_at"] = now
            revised_kind = "pending_update"
        else:
            upd["content"] = body
            ad["original_body"] = body
            ad["ack_body"] = body          # 自分の更新をダイジェストで「ユーザー編集」と誤報しない
            ad["ack_status"] = "pending"
            if intent:
                ad["intent"] = intent.strip() or ad.get("intent")
            if to_name:
                ad["to_name"] = to_name.strip() or ad.get("to_name")
            ad["attachments"] = new_files
            ad["revision"] = int(ad.get("revision") or 1) + 1
            ad["dan_updated_at"] = now
            ad["pending_update"] = None
            revised_kind = "replaced"
        if sender:
            ad["sender"] = sender
        if ad.get("intent"):
            upd["title"] = f"{channel_label('collab')}: {ad.get('to_name') or ad.get('to')} / {ad['intent']}"[:255]
        upd["action_data"] = ad
        r = self.sb.table("dan_proposals").update(upd).eq("id", row["id"]).execute()
        out = dict(r.data[0])
        out["_revised"] = revised_kind
        return out

    def _stage_collab_attachments(self, collab_room_id: Optional[str], attachments: list) -> list:
        """propose 時点で添付を窓口の保存先（uploads/collab/<room>/）へ写し、配信URLにする。
        カードでその場でプレビューでき、送信時は同じファイルを files[] として相手へ渡す。"""
        if not collab_room_id:
            raise ValueError("添付を付けるには collab_room_id が必要です")
        import mimetypes
        import os
        import shutil
        import uuid
        from pathlib import Path
        from app.services.video_faststart import faststart_inplace
        root = Path(__file__).resolve().parent.parent.parent
        dest_dir = root / "uploads" / "collab" / collab_room_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        out: list[dict] = []
        for item in attachments or []:
            src = (item.get("path") if isinstance(item, dict) else str(item or "")).strip()
            if not src:
                continue
            if src.startswith("/api/v1/collab/files/") or src.startswith("http://") or src.startswith("https://"):
                # 既に配信URL（窓口にアップロード済み等）ならそのまま
                name = (item.get("name") if isinstance(item, dict) else None) or src.rsplit("/", 1)[-1]
                mtype = (item.get("type") if isinstance(item, dict) else None) or mimetypes.guess_type(name)[0] or "application/octet-stream"
                out.append({"name": name, "url": src, "type": mtype})
                continue
            # /api/v1/files/<name> 形式（本体チャットのアップロード）はローカルの uploads/ に実体がある
            if src.startswith("/api/v1/files/"):
                src = str(root / "uploads" / src[len("/api/v1/files/"):])
            p = Path(src)
            if not p.is_absolute():
                p = root / p
            if not p.exists() or not p.is_file():
                raise ValueError(f"添付ファイルが見つかりません: {src}")
            ext = p.suffix.lower()
            saved = f"{uuid.uuid4()}{ext}"
            dst = dest_dir / saved
            shutil.copy2(p, dst)
            if ext in (".mp4", ".m4v", ".mov"):
                faststart_inplace(dst)
            mtype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            out.append({
                "name": (item.get("name") if isinstance(item, dict) else None) or p.name,
                "url": f"/api/v1/collab/files/{collab_room_id}/{saved}",
                "type": mtype,
                "size": dst.stat().st_size,
            })
        return out

    # ------------------------------------------------------------------
    # 送信 / 送信済み記録 / 破棄
    # ------------------------------------------------------------------
    async def send(self, proposal_id: str, user_id: str, *, sent_by: str) -> dict:
        """DB の現在本文で実送信する。sent_by = "user" | "dan"。

        サーバー送信できないチャネル（LINE 等）でダンが呼んだ場合は送信せず、
        カードを "sending"（送信中・操作不可）にロックして本文を返す。
        ダンは browser で送った後 mark_sent で確定する（失敗したら release で戻す）。
        送信という行為の関門をこの1関数に一本化し、「送ったのに押せるカードが残る」
        状態を作れなくするための設計（2026-08-31 二重送信事故の根本対策）。"""
        row = self.get(proposal_id, user_id)
        if not row:
            raise ValueError("送信案が見つかりません")
        if row["status"] == "sending":
            raise ValueError("この送信案は送信中（ロック済み）です。完了なら mark_sent、失敗なら release。")
        if row["status"] != "pending":
            raise ValueError(f"この送信案は既に {row['status']} です（二重送信防止）")
        ad = dict(row.get("action_data") or {})
        channel = ad.get("channel") or "other"
        if channel not in SERVER_SENDABLE:
            if sent_by != "dan":
                raise ValueError(f"{channel_label(channel)} はサーバーから直接送信できません。")
            return self._claim_for_manual_send(row, ad)
        body = row["content"]
        to = ad.get("to")
        if not to:
            raise ValueError("宛先がありません")

        if channel == "email":
            from app.config import settings
            reply = ad.get("reply_to") or {}
            subject = ad.get("subject") or _reply_subject(reply.get("subject")) or "(件名なし)"
            from_name = ad.get("from_name") or settings.DAN_DEFAULT_FROM_NAME
            acct = (ad.get("from_account") or "").strip().lower().lstrip("@")
            if acct in ("gmail2", "icloud"):
                # 相手が普段やり取りしているアドレスから出す。send_tracked_email が
                # スレッド返信ヘッダ・送信済みフォルダへの控え・返信照合まで面倒を見る。
                from app.services.email_send import send_tracked_email
                await asyncio.to_thread(
                    send_tracked_email, to, subject, body,
                    user_id=user_id, origin_room_id=row["source_room_id"],
                    from_name=from_name, from_account=acct,
                    in_reply_to=reply.get("message_id"),
                )
            else:
                from app.services.inquiry_notify import _send_smtp, OWNER_REPLY_TO
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

        if channel in ("instagram_dm", "instagram_comment"):
            await self._send_instagram(row, ad, user_id=user_id, sent_by=sent_by, proposal_id=proposal_id)

        if channel == "collab":
            await self._send_collab(row, ad)

        return self._finalize_sent(row, ad, sent_by=sent_by)

    async def _send_collab(self, row: dict, ad: dict) -> None:
        """コラボチャット（外部窓口）へ送る。sandbox の内部エンドポイントが
        保存＋WSリアルタイム配信＋ゲストへのPush通知まで行う。sandbox 停止中でも
        取りこぼさないよう DB 直書きにフォールバック（次回読み込みで相手に見える）。"""
        collab_room_id = (
            (ad.get("reply_to") or {}).get("collab_room_id")
            or (ad.get("target") or {}).get("collab_room_id")
        )
        if not collab_room_id:
            raise ValueError("collab_room_id が未指定です（送信先コラボルームのID）")
        body = row["content"]
        files = [f for f in (ad.get("attachments") or []) if isinstance(f, dict) and f.get("url")]
        # 名義: "owner" ならユーザー本人の発言として届く（表示名も本人）。既定はダン
        as_owner = (ad.get("sender") or "dan") == "owner"
        sender_type = "owner" if as_owner else "dan_owner"
        sender_name = "ダン"
        if as_owner:
            sender_name = await self._owner_display_name(row.get("user_id"))
        import os
        import httpx
        sandbox_port = os.environ.get("DAN_SANDBOX_PORT", "8000")
        payload = {"room_id": collab_room_id, "content": body, "sender_name": sender_name,
                   "sender_type": sender_type}
        if files:
            payload["files"] = files
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"http://127.0.0.1:{sandbox_port}/api/v1/collab/internal/send",
                    json=payload,
                )
                r.raise_for_status()
                ad["send_result"] = r.json()
        except Exception:
            logger.warning("collab internal send failed (sandbox down?); writing to DB directly",
                           exc_info=True)
            from app.services.collab_service import CollabService
            metadata: dict[str, Any] = {"via": "outbound_card"}
            if files:
                metadata["files"] = files
                metadata["file"] = files[0]
            msg = await CollabService().send_message(
                room_id=collab_room_id, sender_type=sender_type, sender_name=sender_name,
                content=body, metadata=metadata,
            )
            ad["send_result"] = {"message_id": msg["id"], "delivery": "db_only"}

    async def _owner_display_name(self, user_id: Optional[str]) -> str:
        try:
            r = self.sb.table("users").select("display_name,email").eq("id", user_id).limit(1).execute()
            if r.data:
                return r.data[0].get("display_name") or (r.data[0].get("email") or "").split("@")[0] or "オーナー"
        except Exception:
            pass
        return "オーナー"

    async def _send_instagram(self, row: dict, ad: dict, *, user_id: str, sent_by: str, proposal_id: str) -> None:
        """Instagram DM / コメントを巡回用プロファイルから内部APIで送る。"""
        from app.services import instagram_send
        channel = ad.get("channel")
        reply = ad.get("reply_to") or {}
        target = ad.get("target") or {}
        account = ad.get("from_account") or reply.get("account")
        if not account:
            try:
                from app.services.instagram_poller import _watched_accounts
                accs = _watched_accounts(user_id)
                if len(accs) == 1:
                    account = accs[0]
            except Exception:
                pass
        if not account:
            raise ValueError("どのInstagramアカウントから送るか（from_account）が未指定です")
        body = row["content"]
        if channel == "instagram_dm":
            handle = (ad.get("to") or "").lstrip("@")
            res = await instagram_send.send_dm(
                account, body, thread_id=reply.get("thread_id"), handle=handle or None, user_id=user_id,
            )
            ad["send_result"] = res
            try:
                from app.services.external_message_routing import get_external_message_routing_service
                await get_external_message_routing_service().record_outbound(
                    user_id=user_id, channel="instagram", origin_room_id=row["source_room_id"],
                    external_account_id=account, external_recipient_id=(res.get("handle") or handle or "").lower() or None,
                    external_thread_id=res.get("thread_id") or reply.get("thread_id"),
                    external_message_id=res.get("item_id"),
                    metadata={"via": "outbound_card", "proposal_id": proposal_id, "sent_by": sent_by},
                )
            except Exception:
                logger.warning("record_outbound (instagram) failed for %s", proposal_id, exc_info=True)
        else:
            post_url = target.get("url") or reply.get("post_url")
            if not post_url:
                raise ValueError("コメント先の投稿URL（target_url / reply_to_post_url）がありません")
            res = await instagram_send.post_comment(
                account, body, post_url=post_url, reply_to_comment_id=reply.get("comment_id"), user_id=user_id,
            )
            ad["send_result"] = {**res, "post_url": post_url}
        ad["from_account"] = account

    def _claim_for_manual_send(self, row: dict, ad: dict) -> dict:
        """手動チャネルの送信前ロック。pending → sending（編集・ボタン無効）。
        以後ダンが mark_sent を忘れても「押せるカード」には戻らない（fail-safe）。"""
        ad["claimed_at"] = _now()
        r = self.sb.table("dan_proposals").update({
            "status": "sending", "action_data": ad,
        }).eq("id", row["id"]).eq("status", "pending").execute()
        if not r.data:
            raise ValueError("ロックに失敗しました（他所で状態が変わった可能性）")
        return r.data[0]

    def release(self, proposal_id: str, user_id: str) -> dict:
        """手動送信に失敗した時のロック解除。sending → pending に戻す。"""
        row = self.get(proposal_id, user_id)
        if not row:
            raise ValueError("送信案が見つかりません")
        if row["status"] != "sending":
            raise ValueError(f"この送信案は sending ではなく {row['status']} です")
        ad = dict(row.get("action_data") or {})
        ad.pop("claimed_at", None)
        r = self.sb.table("dan_proposals").update({
            "status": "pending", "action_data": ad,
        }).eq("id", proposal_id).execute()
        return r.data[0]

    def mark_sent(self, proposal_id: str, user_id: str, *, sent_by: str = "dan", note: Optional[str] = None) -> dict:
        """ダンが browser 等で自力送信した後の記録（本文は DB の現在本文）。"""
        row = self.get(proposal_id, user_id)
        if not row:
            raise ValueError("送信案が見つかりません")
        if row["status"] not in ("pending", "sending"):
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
        if (ad.get("channel") or "") != "collab":
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
        # collab は送信結果が窓口の会話自体に残るので、本体チャットに📤行を出さない。
        if (ad.get("channel") or "") != "collab":
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
            # sending（送信中ロック）は確定されるまで毎ターン督促する（ack で黙らせない）
            if status != "sending" and ad.get("ack_status") == status and ad.get("ack_body") == body:
                continue
            label = f"{channel_label(ad.get('channel'))} → {ad.get('to_name') or ad.get('to')}"
            if ad.get("subject"):
                label += f"「{ad['subject']}」"
            if status == "pending":
                lines.append(
                    f"- 送信案 {row['id']}（{label}）: ユーザーが本文を編集した（まだ未送信）。現在の本文:\n{body}"
                )
            elif status == "sending":
                lines.append(
                    f"- 送信案 {row['id']}（{label}）: 送信中ロックのまま未確定。あなたが browser で送信済みなら"
                    " compose_message(action=\"mark_sent\") で確定、送れていないなら action=\"release\" で下書きに戻すこと。"
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
        """カード行（`[送信案: id]`）や送信/破棄の控えを部屋ログへ追記する。

        このサービスは MCP 子プロセスで動くことが多い。DB に直接書くと core の
        押し込みフィードが知らず、画面は一覧を取り直すまでカードを出せない
        （2026-09-11 の「カードが出ない」）。追記は room_log 経由で core に一本化。
        """
        if not room_id:
            return
        try:
            from app.services.room_log import append as append_room_log
            append_room_log(room_id, content, sender_type="ai", sender_id=None)
        except Exception:
            logger.warning("post room message failed room=%s", room_id, exc_info=True)


def get_outbound_message_service() -> OutboundMessageService:
    return OutboundMessageService()
