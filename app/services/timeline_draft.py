"""Timeline draft store — the agent NEVER edits the live timeline.

A draft is a snapshot of one content's sequence taken at job start. Every agent
tool operates on the draft file; the live contents.json is untouched until
commit_draft(), which re-validates the whole draft and applies it with
compare-and-swap (the live sequence must still hash to what the draft was cut
from — a manual edit during the job turns into an explicit CONFLICT, never a
silent overwrite). Assets generated during the job are tracked on the draft so
a discard/failed commit can garbage-collect them.

Layout: {room_dir}/drafts/{draft_id}.json
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "uploads" / "production-assets"


def _room_dir(room_id: str) -> Path:
    return UPLOAD_ROOT / room_id


def _drafts_dir(room_id: str) -> Path:
    d = _room_dir(room_id) / "drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sequence_hash(sequence: dict[str, Any]) -> str:
    """Canonical content hash used for compare-and-swap at commit time."""
    blob = json.dumps(sequence, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


class ContentsLock:
    """Exclusive file lock around contents.json read-modify-write. Lock file +
    O_EXCL with retries — works across processes on Windows without extra deps."""

    def __init__(self, room_id: str, timeout: float = 10.0):
        self.path = _room_dir(room_id) / "contents.lock"
        self.timeout = timeout
        self._fd: int | None = None

    def __enter__(self):
        deadline = time.time() + self.timeout
        while True:
            try:
                self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, str(os.getpid()).encode())
                return self
            except FileExistsError:
                # stale lock (holder died): break locks older than 30s
                try:
                    if time.time() - self.path.stat().st_mtime > 30:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.time() > deadline:
                    raise TimeoutError(f"contents.json lock timeout: {self.path}")
                time.sleep(0.1)

    def __exit__(self, *exc):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def _read_contents_raw(room_id: str) -> list[dict[str, Any]]:
    p = _room_dir(room_id) / "contents.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def _write_contents_raw(room_id: str, contents: list[dict[str, Any]]) -> None:
    p = _room_dir(room_id) / "contents.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(contents, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def _find_content(contents: list[dict[str, Any]], content_id: str) -> dict[str, Any] | None:
    for c in contents:
        if str(c.get("id")) == str(content_id):
            return c
    return None


def _content_sequence(content: dict[str, Any]) -> dict[str, Any] | None:
    timeline = content.get("timeline") if isinstance(content.get("timeline"), dict) else None
    seq = timeline.get("sequence") if isinstance(timeline, dict) else None
    return seq if isinstance(seq, dict) else None


def draft_path(room_id: str, draft_id: str) -> Path:
    return _drafts_dir(room_id) / f"{draft_id}.json"


def create_draft(room_id: str, content_id: str, job_id: str = "") -> dict[str, Any]:
    """Snapshot the content's sequence into a new draft. Returns the draft dict."""
    with ContentsLock(room_id):
        contents = _read_contents_raw(room_id)
        content = _find_content(contents, content_id)
        if content is None:
            raise ValueError(f"content not found: {content_id}")
        seq = _content_sequence(content)
        if seq is None:
            raise ValueError(f"content has no sequence: {content_id}")
        draft = {
            "draft_id": uuid.uuid4().hex[:12],
            "room_id": room_id,
            "content_id": content_id,
            "job_id": job_id,
            "base_hash": sequence_hash(seq),
            "created_at": time.time(),
            "sequence": json.loads(json.dumps(seq)),  # deep copy
            "generated_asset_ids": [],
            "log": [],
        }
    p = draft_path(room_id, draft["draft_id"])
    p.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    return draft


def load_draft(room_id: str, draft_id: str) -> dict[str, Any]:
    p = draft_path(room_id, draft_id)
    if not p.exists():
        raise ValueError(f"draft not found: {draft_id}")
    return json.loads(p.read_text(encoding="utf-8"))


def save_draft(draft: dict[str, Any]) -> None:
    p = draft_path(draft["room_id"], draft["draft_id"])
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def track_generated_asset(draft: dict[str, Any], asset_id: str) -> None:
    ids = draft.setdefault("generated_asset_ids", [])
    if asset_id not in ids:
        ids.append(asset_id)
    save_draft(draft)


def commit_draft(room_id: str, draft_id: str, validate) -> dict[str, Any]:
    """Validate then apply the draft to the live content with compare-and-swap.

    `validate` is a callable(sequence, room_id) -> list[str] of problems; commit
    is refused while any problem remains. Returns {ok, conflict, problems}.
    On success the draft file is marked committed (kept for audit/undo)."""
    draft = load_draft(room_id, draft_id)
    problems = validate(draft["sequence"], room_id)
    if problems:
        return {"ok": False, "conflict": False, "problems": problems}
    with ContentsLock(room_id):
        contents = _read_contents_raw(room_id)
        content = _find_content(contents, draft["content_id"])
        if content is None:
            return {"ok": False, "conflict": False, "problems": ["content disappeared"]}
        live_seq = _content_sequence(content)
        live_hash = sequence_hash(live_seq) if live_seq else ""
        if live_hash != draft["base_hash"]:
            return {
                "ok": False,
                "conflict": True,
                "problems": [
                    "ジョブ実行中にタイムラインが手動編集されています。上書きせず中止しました"
                    f"（base={draft['base_hash'][:8]} live={live_hash[:8]}）。"
                ],
            }
        # single-writer swap
        content.setdefault("timeline", {})["sequence"] = draft["sequence"]
        _write_contents_raw(room_id, contents)
    draft["committed_at"] = time.time()
    save_draft(draft)
    return {"ok": True, "conflict": False, "problems": []}


def discard_draft(room_id: str, draft_id: str, delete_generated_assets) -> None:
    """Drop the draft; garbage-collect assets that were generated for it.
    `delete_generated_assets` is a callable(room_id, list[str])."""
    try:
        draft = load_draft(room_id, draft_id)
    except ValueError:
        return
    gen = draft.get("generated_asset_ids") or []
    if gen and not draft.get("committed_at"):
        try:
            delete_generated_assets(room_id, gen)
        except Exception:  # noqa: BLE001 — GC must not mask the discard
            pass
    draft["discarded_at"] = time.time()
    save_draft(draft)
