"""
成果物ページ本文（BlockNote ブロック配列）の保存・差分・通知。

役割:
  - 本文と作業チェックの正本を artifact_documents に置く（ブラウザ内保存を廃止）
  - 保存ごとに版を進め、履歴 (artifact_document_revisions) を残す
  - ページ上での編集差分を pending_changes に積む（部屋への通知は既定で無効。
    ダンは必要な時に GET /markdown で最新を読む。2026-09-05 ユーザー指示で通知停止）
  - ダン向けに Markdown 化（scripts/artifact_doc.py と GET /markdown が使う）

ポーラーは sandbox の lifespan から start_document_notifier() で起動する。
通知が無効（既定）のときは、溜まった pending を静かに片付けるだけで部屋には何も送らない。
DAN_ARTIFACT_DOC_NOTIFIER_ENABLED=1 で以前の「静かになったら 1 通」通知に戻せる。
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

TABLE = "artifact_documents"
REVISIONS = "artifact_document_revisions"

NOTIFY_POLL_INTERVAL = 20      # 秒。ポーラーの周期
NOTIFY_QUIET_SECONDS = 90      # 最後の保存からこれだけ静かになったら通知する
NOTIFY_MAX_LINES = 14          # 1 通に載せる差分行の上限
NOTIFY_ENABLED = os.environ.get("DAN_ARTIFACT_DOC_NOTIFIER_ENABLED", "0") == "1"  # 既定で通知しない
TEXT_CLIP = 60                 # 差分行の本文の切り詰め

TYPE_LABEL = {
    "heading": "見出し",
    "checkListItem": "やること",
    "quote": "補足",
    "bulletListItem": "項目",
    "numberedListItem": "項目",
    "paragraph": "文",
    "table": "表",
}


# ---------------------------------------------------------------- ブロック走査

def _inline_text(content: Any) -> str:
    """BlockNote の inline content / table content から素の文字列を取り出す。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if content.get("type") == "tableContent":
            rows = []
            for row in content.get("rows") or []:
                cells = []
                for cell in row.get("cells") or []:
                    if isinstance(cell, dict) and "content" in cell:
                        cells.append(_inline_text(cell.get("content")))
                    else:
                        cells.append(_inline_text(cell))
                rows.append(" | ".join(cells))
            return "\n".join(rows)
        if content.get("type") == "link":
            return _inline_text(content.get("content"))
        if "text" in content:
            return str(content.get("text") or "")
        return ""
    if isinstance(content, list):
        return "".join(_inline_text(c) for c in content)
    return str(content)


def flatten_blocks(blocks: List[dict], depth: int = 0) -> List[dict]:
    """ネストしたブロックを表示順の平坦なリストにする。"""
    out: List[dict] = []
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        props = b.get("props") or {}
        btype = str(b.get("type") or "paragraph")
        out.append(
            {
                "id": str(b.get("id") or ""),
                "type": btype,
                "text": _inline_text(b.get("content")).strip(),
                "checked": bool(props.get("checked")) if btype == "checkListItem" else None,
                "level": int(props.get("level") or 1) if btype == "heading" else 0,
                "depth": depth,
            }
        )
        out.extend(flatten_blocks(b.get("children") or [], depth + 1))
    return out


def blocks_to_markdown(blocks: List[dict], title: str = "") -> str:
    lines: List[str] = []
    if title:
        lines.append("# " + title)
        lines.append("")
    numbered = 0
    for f in flatten_blocks(blocks):
        indent = "  " * f["depth"]
        t, text = f["type"], f["text"]
        if t == "heading":
            numbered = 0
            lines.append("")
            lines.append("#" * min(6, f["level"] + 1) + " " + text)
        elif t == "checkListItem":
            numbered = 0
            mark = "x" if f["checked"] else " "
            lines.append(indent + "- [" + mark + "] " + text + "  <!-- id:" + f["id"] + " -->")
        elif t == "bulletListItem":
            numbered = 0
            lines.append(indent + "- " + text)
        elif t == "numberedListItem":
            numbered += 1
            lines.append(indent + str(numbered) + ". " + text)
        elif t == "quote":
            numbered = 0
            lines.append(indent + "> " + text)
        elif t == "table":
            numbered = 0
            for row in text.split("\n"):
                lines.append(indent + "| " + row + " |")
        elif t == "divider":
            lines.append("---")
        else:
            numbered = 0
            lines.append(indent + text if text else "")
    return "\n".join(lines).strip() + "\n"


def checklist_stats(blocks: List[dict]) -> Dict[str, int]:
    items = [f for f in flatten_blocks(blocks) if f["type"] == "checkListItem"]
    return {"total": len(items), "done": sum(1 for f in items if f["checked"])}


def _parse_ts(value: Any) -> Optional[datetime]:
    """Supabase の時刻文字列を読む。

    PostgREST は小数秒の末尾ゼロを落として返す（例 ``05:27:18.01016+00:00``）。
    Python 3.10 の fromisoformat は小数部が 3 桁か 6 桁でないと失敗するので、6 桁に揃える。
    """
    if not value:
        return None
    s = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    import re

    m = re.match(r"^(.*?\d{2}:\d{2}:\d{2})\.(\d+)(.*)$", s)
    if not m:
        return None
    frac = (m.group(2) + "000000")[:6]
    try:
        dt = datetime.fromisoformat(m.group(1) + "." + frac + m.group(3))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- 差分

def _clip(s: str) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= TEXT_CLIP else s[: TEXT_CLIP - 1] + "…"


def merge_pending(pending: Dict[str, dict], old_blocks: List[dict], new_blocks: List[dict]) -> Dict[str, dict]:
    """前回の通知以降の差分を block_id 単位で累積する。

    1 つのブロックを何度打ち直しても「最初の状態 → 最後の状態」の 1 行に畳む。
    追加して消した・元に戻した、はゼロ差分として消える。
    """
    old = {f["id"]: f for f in flatten_blocks(old_blocks) if f["id"]}
    new = {f["id"]: f for f in flatten_blocks(new_blocks) if f["id"]}
    pending = dict(pending or {})
    for bid in set(old) | set(new):
        o, n = old.get(bid), new.get(bid)
        if o and n and o["text"] == n["text"] and o["checked"] == n["checked"] and o["type"] == n["type"]:
            continue  # このブロックは今回変わっていない
        entry = pending.get(bid)
        if not entry:
            entry = {
                "existed_before": bool(o),
                "before_text": o["text"] if o else "",
                "before_checked": o["checked"] if o else None,
                "type": (o or n or {}).get("type", "paragraph"),
            }
        entry["exists_after"] = bool(n)
        entry["after_text"] = n["text"] if n else ""
        entry["after_checked"] = n["checked"] if n else None
        if n:
            entry["type"] = n["type"]
        zero = entry["existed_before"] == entry["exists_after"] and (
            not entry["exists_after"]
            or (entry["before_text"] == entry["after_text"] and entry["before_checked"] == entry["after_checked"])
        )
        if zero:
            pending.pop(bid, None)
        else:
            pending[bid] = entry
    return pending


def describe_pending(pending: Dict[str, dict]) -> List[str]:
    lines: List[str] = []
    for entry in pending.values():
        label = TYPE_LABEL.get(entry.get("type", ""), "文")
        before, after = _clip(entry.get("before_text", "")), _clip(entry.get("after_text", ""))
        if not entry.get("existed_before") and entry.get("exists_after"):
            if after:
                lines.append("追加（" + label + "）: 「" + after + "」")
        elif entry.get("existed_before") and not entry.get("exists_after"):
            if before:
                lines.append("削除（" + label + "）: 「" + before + "」")
        else:
            if entry.get("type") == "checkListItem" and entry.get("before_checked") != entry.get("after_checked"):
                state = "完了にした" if entry.get("after_checked") else "未完了に戻した"
                lines.append(state + ": 「" + (after or before) + "」")
            if before != after:
                if before and after:
                    lines.append("書き換え（" + label + "）: 「" + before + "」→「" + after + "」")
                elif after:
                    lines.append("追記（" + label + "）: 「" + after + "」")
                elif before:
                    lines.append("消去（" + label + "）: 「" + before + "」")
    return lines


class ConflictError(Exception):
    def __init__(self, current_version: int):
        super().__init__("document changed (current v%d)" % current_version)
        self.current_version = current_version


# ---------------------------------------------------------------- サービス

class ArtifactDocumentsService:
    def __init__(self) -> None:
        self.supabase = get_supabase_client().client

    # --- 読み ---
    def get_row(self, slug: str) -> Optional[dict]:
        r = self.supabase.table(TABLE).select("*").eq("artifact_slug", slug).limit(1).execute()
        return r.data[0] if r.data else None

    async def get(self, slug: str) -> Optional[dict]:
        return await asyncio.to_thread(self.get_row, slug)

    def public_view(self, row: dict) -> dict:
        return {
            "artifact_slug": row["artifact_slug"],
            "title": row.get("title") or "",
            "blocks": row.get("blocks") or [],
            "version": int(row.get("version") or 1),
            "updated_at": row.get("updated_at"),
            "last_saved_at": row.get("last_saved_at"),
            "last_editor": row.get("last_editor"),
        }

    def markdown(self, row: dict) -> str:
        stats = checklist_stats(row.get("blocks") or [])
        head = "<!-- slug:%s version:%s updated:%s checklist:%d/%d -->\n" % (
            row["artifact_slug"],
            row.get("version"),
            row.get("last_saved_at") or row.get("updated_at"),
            stats["done"],
            stats["total"],
        )
        return head + blocks_to_markdown(row.get("blocks") or [], row.get("title") or "")

    # --- 権限 ---
    def verify_key(self, row: dict, edit_key: Optional[str]) -> bool:
        stored = row.get("edit_key") or ""
        return bool(stored and edit_key and secrets.compare_digest(stored, edit_key))

    def is_owner(self, row: dict, user_id: Optional[str]) -> bool:
        return bool(user_id and str(row.get("created_by") or "") == str(user_id))

    # --- 作成 / 種付け ---
    def ensure(
        self,
        slug: str,
        *,
        title: str,
        blocks: List[dict],
        room_id: Optional[str],
        owner_user_id: Optional[str],
        replace: bool = False,
    ) -> dict:
        """無ければ作る。replace=True なら本文を差し替える（ダンの編集扱い・通知しない）。"""
        row = self.get_row(slug)
        now = datetime.now(timezone.utc).isoformat()
        if not row:
            payload = {
                "artifact_slug": slug,
                "title": title,
                "blocks": blocks,
                "version": 1,
                "edit_key": secrets.token_urlsafe(18),
                "room_id": room_id,
                "created_by": owner_user_id,
                "last_editor": "dan",
                "last_saved_at": now,
            }
            r = self.supabase.table(TABLE).insert(payload).execute()
            row = r.data[0]
            self._insert_revision(row["id"], 1, "dan", "初版", blocks)
            return row
        if replace:
            return self.save_sync(slug, blocks, title=title, editor="dan", base_version=None)
        return row

    def _insert_revision(self, document_id: str, version: int, editor: str, summary: str, blocks: List[dict]) -> None:
        self.supabase.table(REVISIONS).insert(
            {"document_id": document_id, "version": version, "editor": editor, "summary": summary[:2000], "blocks": blocks}
        ).execute()

    # --- 保存 ---
    def save_sync(
        self,
        slug: str,
        blocks: List[dict],
        *,
        title: Optional[str],
        editor: str,
        base_version: Optional[int],
    ) -> dict:
        row = self.get_row(slug)
        if not row:
            raise LookupError("document not found")
        current_version = int(row.get("version") or 1)
        if base_version is not None and base_version < current_version and editor != "dan":
            raise ConflictError(current_version)

        old_blocks = row.get("blocks") or []
        diff_now = merge_pending({}, old_blocks, blocks)
        title_changed = title is not None and title != (row.get("title") or "")
        if not diff_now and not title_changed:
            return {**row, "changed": False, "changes": []}

        now = datetime.now(timezone.utc).isoformat()
        new_version = current_version + 1
        lines = describe_pending(diff_now)
        if title_changed:
            lines.insert(0, "題名: 「" + _clip(row.get("title") or "") + "」→「" + _clip(title or "") + "」")
        update: Dict[str, Any] = {
            "blocks": blocks,
            "version": new_version,
            "last_editor": editor,
            "last_saved_at": now,
        }
        if title is not None:
            update["title"] = title
        if editor != "dan":
            # ダン自身の編集は通知しない。ページ側の編集だけ差分を積む。
            pending = merge_pending(row.get("pending_changes") or {}, old_blocks, blocks)
            update["pending_changes"] = pending
            if pending or title_changed:
                if not row.get("pending_since"):
                    update["pending_since"] = now
                    update["pending_from_version"] = current_version
            else:
                update["pending_since"] = None
                update["pending_from_version"] = None
        r = self.supabase.table(TABLE).update(update).eq("id", row["id"]).execute()
        self._insert_revision(row["id"], new_version, editor, "\n".join(lines) or "（差分なし）", blocks)
        saved = r.data[0] if r.data else {**row, **update}
        return {**saved, "changed": True, "changes": lines}

    async def save(self, slug: str, blocks: List[dict], *, title: Optional[str], editor: str, base_version: Optional[int]) -> dict:
        return await asyncio.to_thread(self.save_sync, slug, blocks, title=title, editor=editor, base_version=base_version)

    async def revisions(self, slug: str, limit: int = 30) -> List[dict]:
        row = await self.get(slug)
        if not row:
            return []
        r = (
            self.supabase.table(REVISIONS)
            .select("version,editor,summary,created_at")
            .eq("document_id", row["id"])
            .order("version", desc=True)
            .limit(limit)
            .execute()
        )
        return r.data or []

    # --- 通知 ---
    def flush_pending_sync(self, quiet_seconds: int = NOTIFY_QUIET_SECONDS, notify: bool = NOTIFY_ENABLED) -> int:
        """静かになった編集差分を片付ける。notify=True なら部屋へ 1 通で送る。送った件数を返す。"""
        r = self.supabase.table(TABLE).select("*").not_.is_("pending_since", "null").execute()
        sent = 0
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=quiet_seconds)
        for row in r.data or []:
            last_dt = _parse_ts(row.get("last_saved_at") or row.get("updated_at"))
            if last_dt is None:
                # 時刻が読めない行は「今保存された」扱いにして、次の周期で再判定する
                # （読めない＝即通知、にすると打鍵の途中で通知が飛ぶ）
                continue
            if last_dt > cutoff:
                continue
            if notify and self._notify_room(row):
                sent += 1
            self.supabase.table(TABLE).update(
                {"pending_changes": {}, "pending_since": None, "pending_from_version": None}
            ).eq("id", row["id"]).execute()
        return sent

    def build_notification(self, row: dict) -> Optional[str]:
        lines = describe_pending(row.get("pending_changes") or {})
        if not lines:
            return None
        stats = checklist_stats(row.get("blocks") or [])
        head = "「%s」がページ上で編集されました（v%s → v%s）" % (
            row.get("title") or row["artifact_slug"],
            row.get("pending_from_version") or "?",
            row.get("version"),
        )
        shown = lines[:NOTIFY_MAX_LINES]
        body = "\n".join("- " + l for l in shown)
        if len(lines) > NOTIFY_MAX_LINES:
            body += "\n- …ほか%d件" % (len(lines) - NOTIFY_MAX_LINES)
        foot = "\n\nやること: %d / %d 完了。内容は読み込み済みです。関係する項目があれば次の返信で直します。" % (
            stats["done"],
            stats["total"],
        )
        return head + "\n\n" + body + foot

    def _notify_room(self, row: dict) -> bool:
        room_id, user_id = row.get("room_id"), row.get("created_by")
        if not room_id or not user_id:
            return False
        content = self.build_notification(row)
        if not content:
            return False
        try:
            from app.services.chat_service import ChatService

            asyncio.run(ChatService().send_dan_ai_message(user_id, content, room_id=room_id))
            return True
        except Exception:
            logger.exception("artifact document notify failed (slug=%s)", row.get("artifact_slug"))
            return False


# ---------------------------------------------------------------- ポーラー

_started = False


async def _notifier_loop() -> None:
    await asyncio.sleep(10)
    while True:
        try:
            sent = await asyncio.to_thread(ArtifactDocumentsService().flush_pending_sync)
            if sent:
                logger.info("artifact document notifications sent: %d", sent)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("artifact document notifier cycle failed: %s", e)
        await asyncio.sleep(NOTIFY_POLL_INTERVAL)


def start_document_notifier() -> Optional["asyncio.Task"]:
    global _started
    if _started:
        return None
    _started = True
    task = asyncio.get_event_loop().create_task(_notifier_loop())
    logger.info(
        "artifact document notifier started (interval=%ss, quiet=%ss, notify=%s)",
        NOTIFY_POLL_INTERVAL,
        NOTIFY_QUIET_SECONDS,
        NOTIFY_ENABLED,
    )
    return task
