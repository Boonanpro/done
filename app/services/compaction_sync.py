"""
Compaction Sync - Claude Code のコンパクション（会話の短縮）を daily memory にミラーリング

Claude Code の .jsonl ファイルから compact_boundary を検出し、
~/.dan/workspace/memory/YYYY-MM-DD.md に追記する。UUID単位で重複防止。

記録の形は3通りある（2026-10-07 実物で確認）:
1. 旧形式: 要約の user メッセージが boundary の直接の子（parentUuid == boundary.uuid）。
2. 現行の組み込み要約: boundary に compactMetadata があり、要約の user メッセージは
   `isCompactSummary: true`。boundary の直接の子ではない（間に attachment 等が挟まる）。
   2026-06 以降この形になり、旧ロジックでは1件も写せていなかった。
3. Jev で短縮（services/claude-plugins/dan-compact）: boundary はあるが要約メッセージが無い。
   残した元の会話がそのまま続く。何を捨てたかはプラグインの台帳
   (~/.dan/workspace/memory/.compact_jev_ledger.json の last) に残るので、それを写す。
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

WORKSPACE_DIR = Path.home() / ".dan" / "workspace"
COMPACTION_SYNC_STATE_PATH = WORKSPACE_DIR / "memory" / ".compaction_sync_state.json"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
DEFAULT_LEDGER_PATH = WORKSPACE_DIR / "memory" / ".compact_jev_ledger.json"

# 初めて見た boundary がこれより古ければ書かずに同期済みにする（形式変更で溜まった
# 2026-06 以降の要約を、初回に数百件まとめて古い日付の memory へ流し込まないため）。
BACKFILL_WINDOW = timedelta(days=3)
# Jev の台帳の last.at が boundary の時刻とこれ以内なら同じ短縮とみなす
LEDGER_MATCH_WINDOW = timedelta(minutes=5)


def sync_compaction_summaries() -> int:
    """
    Claude Code の .jsonl ファイルからコンパクションを読み取り、
    .dan/workspace/memory/YYYY-MM-DD.md にミラーリングする。

    Returns:
        新たに同期した件数（書いた件数。古くて書かなかった分は含まない）
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
        written: list[str] = []
        ledger_last = _read_ledger_last()

        # すべての .jsonl ファイルを走査
        jsonl_files = list(CLAUDE_PROJECTS_DIR.rglob("*.jsonl")) if CLAUDE_PROJECTS_DIR.exists() else []
        for jsonl_path in jsonl_files:
            try:
                _sync_file(jsonl_path, synced_uuids, new_uuids, written, ledger_last)
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
            logger.info(
                f"[compaction_sync] mirrored {len(written)} compaction(s), "
                f"{len(new_uuids) - len(written)} older one(s) marked as seen"
            )

        return len(written)

    except Exception as e:
        logger.warning(f"[compaction_sync] failed: {e}")
        return 0


def _ledger_path() -> Path:
    raw = os.environ.get("DAN_COMPACT_LEDGER_PATH", "").strip()
    return Path(raw) if raw else DEFAULT_LEDGER_PATH


def _read_ledger_last() -> Optional[dict]:
    """Jev 短縮プラグインの台帳の last（最後の短縮の結果）。無ければ None。"""
    try:
        path = _ledger_path()
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        last = data.get("last") if isinstance(data, dict) else None
        return last if isinstance(last, dict) else None
    except Exception:
        return None


def _parse_ts(raw: str) -> Optional[datetime]:
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except Exception:
        return None


def _find_summary(segment: list[dict], boundary_uuid: str) -> Optional[str]:
    """boundary の後ろ（次の boundary まで）から要約メッセージの本文を探す。無ければ None。"""
    for entry in segment:
        msg = entry.get("message", {})
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        if entry.get("isCompactSummary"):
            return content
        if entry.get("parentUuid") == boundary_uuid and (
            "This session is being continued" in content or "summary" in content.lower()
        ):
            return content
    return None


def _describe_verbatim_compaction(meta: dict, ts: Optional[datetime], ledger_last: Optional[dict]) -> str:
    """要約メッセージの無い短縮（Jev で元の会話を残した）を1段落で書く。"""
    pre = meta.get("preTokens")
    post = meta.get("postTokens")
    tokens = f"{pre:,}→{post:,} tokens" if isinstance(pre, int) and isinstance(post, int) else "tokens 不明"
    duration = meta.get("durationMs")
    dur = f"、{duration}ms" if isinstance(duration, (int, float)) else ""
    last = ledger_last or {}
    last_at = _parse_ts(last.get("at", "")) if last else None
    matched = (
        last.get("outcome") == "compacted"
        and ts is not None
        and last_at is not None
        and abs(ts - last_at) <= LEDGER_MATCH_WINDOW
    )
    if matched:
        ratio = last.get("ratio")
        pct = f"{round(float(ratio) * 100)}%減" if isinstance(ratio, (int, float)) else ""
        return (
            f"Jev で短縮（要約なし・発言はそのまま）: 道具の呼び出し {last.get('callsDropped', '?')} 件を捨てた、"
            f"結果 {last.get('resultsDropped', '?')} 件を切り詰めた、{last.get('kept', '?')} 件残した"
            f"（直近 {last.get('pinned', '?')} 件は触らず）。"
            f"{last.get('charsBefore', '?')}字→{last.get('charsAfter', '?')}字 {pct}、{tokens}{dur}、"
            f"Jev 問い合わせ {last.get('requests', '?')} 回・約 {last.get('yen', '?')} 円"
            f"（今月 {last.get('monthYen', '?')} 円 / 上限 {last.get('capJpy', '?')} 円）。"
        )
    return (
        f"要約メッセージの無い短縮（Jev で元の会話を残した短縮の可能性。台帳に一致する記録なし）: {tokens}{dur}。"
    )


def _sync_file(
    jsonl_path: Path,
    synced_uuids: set[str],
    new_uuids: list[str],
    written: Optional[list[str]] = None,
    ledger_last: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> None:
    """1つの .jsonl ファイルからコンパクションを抽出して date.md に追記する"""
    if written is None:
        written = []
    now = now or datetime.now(timezone.utc)

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

    boundary_idx = [
        i for i, e in enumerate(entries)
        if e.get("type") == "system" and e.get("subtype") == "compact_boundary" and e.get("uuid")
    ]
    if not boundary_idx:
        return

    for k, i in enumerate(boundary_idx):
        boundary = entries[i]
        boundary_uuid = boundary["uuid"]
        if boundary_uuid in synced_uuids:
            continue
        end = boundary_idx[k + 1] if k + 1 < len(boundary_idx) else len(entries)
        segment = entries[i + 1:end]

        ts = _parse_ts(boundary.get("timestamp", ""))
        if ts is not None and now - ts > BACKFILL_WINDOW:
            # 古い分は書かずに同期済みにする（初回の流し込み防止）
            synced_uuids.add(boundary_uuid)
            new_uuids.append(boundary_uuid)
            continue
        display_ts = (ts or now).strftime("%Y-%m-%d %H:%M:%S")
        date_str = (ts or now).strftime("%Y-%m-%d")

        summary = _find_summary(segment, boundary_uuid)
        meta = boundary.get("compactMetadata") or {}
        if summary is not None:
            kind = "compaction"
            body = summary.strip()
        else:
            kind = "compaction/jev"
            body = _describe_verbatim_compaction(meta, ts, ledger_last)

        memory_dir = WORKSPACE_DIR / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        log_path = memory_dir / f"{date_str}.md"
        session_id = boundary.get("sessionId", jsonl_path.stem)
        trigger = meta.get("trigger")
        head = f"### {display_ts} [{kind}] session={session_id}" + (f" trigger={trigger}" if trigger else "")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n\n---\n\n{head}\n\n{body}\n")

        synced_uuids.add(boundary_uuid)
        new_uuids.append(boundary_uuid)
        written.append(boundary_uuid)
        logger.debug(f"[compaction_sync] wrote {kind} uuid={boundary_uuid} → {log_path.name}")
