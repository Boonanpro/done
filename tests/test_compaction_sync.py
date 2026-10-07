"""compaction_sync: Claude Code の3通りの短縮記録を memory に写す（落ちない・意味のある行になる）。"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import compaction_sync as cs

NOW = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)


@pytest.fixture
def ws(monkeypatch, tmp_path):
    workspace = tmp_path / "ws"
    monkeypatch.setattr(cs, "WORKSPACE_DIR", workspace)
    monkeypatch.setattr(cs, "COMPACTION_SYNC_STATE_PATH", workspace / "memory" / ".compaction_sync_state.json")
    monkeypatch.setattr(cs, "CLAUDE_PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(cs, "DEFAULT_LEDGER_PATH", workspace / "memory" / ".compact_jev_ledger.json")
    monkeypatch.delenv("DAN_COMPACT_LEDGER_PATH", raising=False)
    (tmp_path / "projects" / "p").mkdir(parents=True)
    return tmp_path


def _write_jsonl(path: Path, entries):
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8")


def _boundary(uuid, ts, meta=None):
    e = {"type": "system", "subtype": "compact_boundary", "uuid": uuid, "timestamp": ts.isoformat().replace("+00:00", "Z"),
         "sessionId": "sess-1", "parentUuid": None}
    if meta is not None:
        e["compactMetadata"] = meta
    return e


def _user(text, uuid, parent, **extra):
    return {"type": "user", "uuid": uuid, "parentUuid": parent, "message": {"role": "user", "content": text}, **extra}


def test_old_format_summary_as_direct_child(ws):
    ts = NOW - timedelta(hours=1)
    _write_jsonl(ws / "projects" / "p" / "a.jsonl", [
        _boundary("b-old", ts),
        _user("This session is being continued from a previous conversation. Summary: did X.", "u1", "b-old"),
    ])
    synced, new, written = set(), [], []
    cs._sync_file(ws / "projects" / "p" / "a.jsonl", synced, new, written, None, now=NOW)
    assert written == ["b-old"]
    text = (ws / "ws" / "memory" / f"{ts:%Y-%m-%d}.md").read_text(encoding="utf-8")
    assert "[compaction] session=sess-1" in text
    assert "did X." in text


def test_current_builtin_summary_is_found_even_when_not_a_direct_child(ws):
    ts = NOW - timedelta(minutes=30)
    _write_jsonl(ws / "projects" / "p" / "b.jsonl", [
        _boundary("b-new", ts, {"trigger": "auto", "preTokens": 967518, "postTokens": 10291}),
        {"type": "attachment", "uuid": "att1", "parentUuid": "b-new"},
        {"type": "attachment", "uuid": "att2", "parentUuid": "att1"},
        _user("This session is being continued from a previous conversation that ran out of context. Summary: 1. Primary Request...",
              "u2", "att2", isCompactSummary=True),
    ])
    synced, new, written = set(), [], []
    cs._sync_file(ws / "projects" / "p" / "b.jsonl", synced, new, written, None, now=NOW)
    assert written == ["b-new"]
    text = (ws / "ws" / "memory" / f"{ts:%Y-%m-%d}.md").read_text(encoding="utf-8")
    assert "[compaction] session=sess-1 trigger=auto" in text
    assert "1. Primary Request" in text


def test_jev_verbatim_compaction_uses_metadata_and_ledger(ws):
    ts = NOW - timedelta(minutes=10)
    ledger_last = {
        "at": (ts - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"), "outcome": "compacted",
        "charsBefore": 180272, "charsAfter": 30760, "callsDropped": 10, "resultsDropped": 0, "kept": 0, "pinned": 2,
        "ratio": 0.8294, "requests": 1, "yen": 0.0185, "monthYen": 0.0185, "capJpy": 100,
    }
    _write_jsonl(ws / "projects" / "p" / "c.jsonl", [
        _user("first prompt", "u0", None),
        _boundary("b-jev", ts, {"trigger": "auto", "preTokens": 69120, "postTokens": 11943, "durationMs": 322}),
        _user("first prompt", "u0b", "b-jev"),          # 残した元の会話がそのまま続く（要約なし）
        {"type": "assistant", "uuid": "a1", "parentUuid": "u0b", "message": {"role": "assistant", "content": [{"type": "text", "text": "answer"}]}},
    ])
    synced, new, written = set(), [], []
    cs._sync_file(ws / "projects" / "p" / "c.jsonl", synced, new, written, ledger_last, now=NOW)
    assert written == ["b-jev"]
    text = (ws / "ws" / "memory" / f"{ts:%Y-%m-%d}.md").read_text(encoding="utf-8")
    assert "[compaction/jev] session=sess-1 trigger=auto" in text
    assert "Jev で短縮" in text
    assert "呼び出し 10 件を捨てた" in text
    assert "180272字→30760字 83%減" in text
    assert "69,120→11,943 tokens、322ms" in text
    assert "約 0.0185 円" in text


def test_jev_compaction_without_matching_ledger_still_writes_a_line(ws):
    ts = NOW - timedelta(minutes=10)
    stale = {"at": (ts - timedelta(hours=2)).isoformat(), "outcome": "compacted", "callsDropped": 99}
    _write_jsonl(ws / "projects" / "p" / "d.jsonl", [
        _boundary("b-jev2", ts, {"trigger": "auto", "preTokens": 50000, "postTokens": 9000}),
        _user("first prompt", "u0b", "b-jev2"),
    ])
    synced, new, written = set(), [], []
    cs._sync_file(ws / "projects" / "p" / "d.jsonl", synced, new, written, stale, now=NOW)
    assert written == ["b-jev2"]
    text = (ws / "ws" / "memory" / f"{ts:%Y-%m-%d}.md").read_text(encoding="utf-8")
    assert "要約メッセージの無い短縮" in text
    assert "50,000→9,000 tokens" in text
    assert "99" not in text


def test_old_boundaries_are_marked_seen_without_writing_and_dedup_holds(ws):
    old = NOW - timedelta(days=10)
    fresh = NOW - timedelta(minutes=5)
    path = ws / "projects" / "p" / "e.jsonl"
    _write_jsonl(path, [
        _boundary("b-old-1", old, {"trigger": "auto"}),
        _user("Summary: ancient", "u9", "b-old-1", isCompactSummary=True),
        _boundary("b-fresh", fresh, {"trigger": "manual"}),
        _user("Summary: recent", "u10", "b-fresh", isCompactSummary=True),
    ])
    synced, new, written = set(), [], []
    cs._sync_file(path, synced, new, written, None, now=NOW)
    assert written == ["b-fresh"]
    assert set(new) == {"b-old-1", "b-fresh"}
    assert not (ws / "ws" / "memory" / f"{old:%Y-%m-%d}.md").exists()
    # 2回目は何も書かない
    new2, written2 = [], []
    cs._sync_file(path, synced, new2, written2, None, now=NOW)
    assert written2 == [] and new2 == []


def test_sync_entry_point_reads_ledger_and_persists_state(ws, monkeypatch):
    ts = datetime.now(timezone.utc) - timedelta(minutes=1)
    ledger = ws / "ws" / "memory" / ".compact_jev_ledger.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps({"month": ts.strftime("%Y-%m"), "yen": 0.01, "runs": 1, "last": {
        "at": ts.isoformat().replace("+00:00", "Z"), "outcome": "compacted", "charsBefore": 10, "charsAfter": 5,
        "callsDropped": 3, "resultsDropped": 1, "kept": 0, "pinned": 2, "ratio": 0.5, "requests": 1, "yen": 0.01,
        "monthYen": 0.01, "capJpy": 100}}), encoding="utf-8")
    _write_jsonl(ws / "projects" / "p" / "f.jsonl", [
        _boundary("b-live", ts, {"trigger": "auto", "preTokens": 100, "postTokens": 50}),
        _user("first prompt", "u0b", "b-live"),
    ])
    assert cs.sync_compaction_summaries() == 1
    state = json.loads((ws / "ws" / "memory" / ".compaction_sync_state.json").read_text(encoding="utf-8"))
    assert state["synced_uuids"] == ["b-live"]
    text = (ws / "ws" / "memory" / f"{ts:%Y-%m-%d}.md").read_text(encoding="utf-8")
    assert "呼び出し 3 件を捨てた" in text
    assert cs.sync_compaction_summaries() == 0


def test_broken_lines_and_missing_dirs_do_not_raise(ws):
    path = ws / "projects" / "p" / "g.jsonl"
    path.write_text("{not json}\n\n" + json.dumps(_boundary("b-x", NOW - timedelta(minutes=1))) + "\n{also broken\n", encoding="utf-8")
    synced, new, written = set(), [], []
    cs._sync_file(path, synced, new, written, None, now=NOW)
    assert written == ["b-x"]


REAL = Path(r"C:\dan-work\devlead_tmp\v7\fire\autowin\after.jsonl")


@pytest.mark.skipif(not REAL.exists(), reason="fire-test transcript not present")
def test_real_hook_compaction_transcript(ws):
    """発火試験で実際にできた .jsonl（Jev が要約を置き換えた後）を通す。"""
    import shutil
    shutil.copy(REAL, ws / "projects" / "p" / "real.jsonl")
    entries = [json.loads(l) for l in REAL.read_text(encoding="utf-8").splitlines() if l.strip()]
    boundary = next(e for e in entries if e.get("subtype") == "compact_boundary")
    ts = cs._parse_ts(boundary["timestamp"])
    synced, new, written = set(), [], []
    cs._sync_file(ws / "projects" / "p" / "real.jsonl", synced, new, written, None, now=ts + timedelta(minutes=1))
    assert written == [boundary["uuid"]]
    text = (ws / "ws" / "memory" / f"{ts:%Y-%m-%d}.md").read_text(encoding="utf-8")
    assert "[compaction/jev]" in text
    meta = boundary["compactMetadata"]
    assert f"{meta['preTokens']:,}→{meta['postTokens']:,} tokens" in text
    assert not any(e.get("isCompactSummary") for e in entries), "the hook replaced the summary: no summary message in the transcript"
