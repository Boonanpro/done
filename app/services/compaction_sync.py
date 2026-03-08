"""
Compaction Sync - Claude Code のコンパクションサマリーを daily memory にミラーリング

Claude Code の .jsonl ファイルから compact_boundary を検出し、
サマリーを ~/.dan/workspace/memory/YYYY-MM-DD.md に追記する。
UUID単位で重複防止。
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

WORKSPACE_DIR = Path.home() / ".dan" / "workspace"
COMPACTION_SYNC_STATE_PATH = WORKSPACE_DIR / "memory" / ".compaction_sync_state.json"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def sync_compaction_summaries() -> int:
    """
    Claude Code の .jsonl ファイルからコンパクションサマリーを読み取り、
    .dan/workspace/memory/YYYY-MM-DD.md にミラーリングする。

    Returns:
        新たに同期したサマリーの件数
    """
    try:
        # 同期済みUUIDを読み込む
        synced_uuids: set[str] = set()
        if COMPACTION_SYNC_STATE_PATH.exists():
            try:
                state = json.loads(COMPACTION_SYNC_STATE_PATH.read_text(encoding="utf-8"))
                synced_uuids = set(state.get("synced_uuids", []))
            except Exception:
                pass

        new_uuids: list[str] = []

        # すべての .jsonl ファイルを走査
        jsonl_files = list(CLAUDE_PROJECTS_DIR.rglob("*.jsonl")) if CLAUDE_PROJECTS_DIR.exists() else []
        for jsonl_path in jsonl_files:
            try:
                _sync_file(jsonl_path, synced_uuids, new_uuids)
            except Exception as e:
                logger.debug(f"[compaction_sync] skip {jsonl_path.name}: {e}")

        # 状態ファイルを更新
        if new_uuids:
            all_uuids = list(synced_uuids | set(new_uuids))
            COMPACTION_SYNC_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            COMPACTION_SYNC_STATE_PATH.write_text(
                json.dumps({"synced_uuids": all_uuids}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(f"[compaction_sync] mirrored {len(new_uuids)} new summary(ies)")

        return len(new_uuids)

    except Exception as e:
        logger.warning(f"[compaction_sync] failed: {e}")
        return 0


def _sync_file(jsonl_path: Path, synced_uuids: set[str], new_uuids: list[str]) -> None:
    """1つの .jsonl ファイルからサマリーを抽出して date.md に追記する"""
    # 全行をパース
    entries: list[dict] = []
    with jsonl_path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    # compact_boundary の uuid をキーにしたマップを作る
    boundaries: dict[str, dict] = {}
    for entry in entries:
        if entry.get("type") == "system" and entry.get("subtype") == "compact_boundary":
            uid = entry.get("uuid", "")
            if uid:
                boundaries[uid] = entry

    if not boundaries:
        return

    # 各 compact_boundary に対応するサマリーメッセージを探す
    for entry in entries:
        parent_uuid = entry.get("parentUuid", "")
        if parent_uuid not in boundaries:
            continue

        boundary = boundaries[parent_uuid]
        boundary_uuid = boundary.get("uuid", "")
        if not boundary_uuid or boundary_uuid in synced_uuids:
            continue

        # user メッセージかつ content が文字列（サマリーテキスト）
        msg = entry.get("message", {})
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        if "This session is being continued" not in content and "summary" not in content.lower():
            continue

        # timestamp から日付を決定
        ts_str = boundary.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            date_str = ts.strftime("%Y-%m-%d")
            display_ts = ts.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            date_str = datetime.now().strftime("%Y-%m-%d")
            display_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # date.md に追記
        memory_dir = WORKSPACE_DIR / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        log_path = memory_dir / f"{date_str}.md"

        session_id = boundary.get("sessionId", jsonl_path.stem)
        entry_text = (
            f"\n\n---\n\n"
            f"### {display_ts} [compaction] session={session_id}\n\n"
            f"{content.strip()}\n"
        )
        with log_path.open("a", encoding="utf-8") as f:
            f.write(entry_text)

        synced_uuids.add(boundary_uuid)
        new_uuids.append(boundary_uuid)
        logger.debug(f"[compaction_sync] wrote summary uuid={boundary_uuid} → {log_path.name}")
