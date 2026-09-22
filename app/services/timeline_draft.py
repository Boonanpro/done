"""Timeline working copies with validated incremental publication.

Tools edit a draft, then publish a complete operation using compare-and-swap.
Preparation-only drafts stay private until final commit. Human saves are adopted
before another operation; concurrent unpublished edits produce a conflict.
Published assets remain available to the live timeline and its undo history.

Layout: {room_dir}/drafts/{draft_id}.json
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "uploads" / "production-assets"
_transaction = ContextVar('timeline_draft_transaction', default=None)


@contextmanager
def edit_transaction(room_id, draft_id):
    """Keep sub-operations in memory; persist once, only after success."""
    if _transaction.get() is not None:
        raise RuntimeError('Nested draft transaction')
    draft = load_draft(room_id, draft_id)
    state = {'key': (room_id, draft_id), 'draft': draft, 'dirty': False}
    token = _transaction.set(state)
    try:
        yield
    except BaseException:
        raise
    else:
        if state['dirty']:
            _transaction.reset(token)
            token = None
            save_draft(state['draft'])
    finally:
        if token is not None:
            _transaction.reset(token)


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
            "base_sequence": json.loads(json.dumps(seq)),
            "generated_asset_ids": [],
            "log": [],
        }
    p = draft_path(room_id, draft["draft_id"])
    p.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    return draft


def load_draft(room_id: str, draft_id: str) -> dict[str, Any]:
    state = _transaction.get()
    if state and state['key'] == (room_id, draft_id):
        return state['draft']
    p = draft_path(room_id, draft_id)
    if not p.exists():
        raise ValueError(f"draft not found: {draft_id}")
    return json.loads(p.read_text(encoding="utf-8"))


def save_draft(draft: dict[str, Any]) -> None:
    state = _transaction.get()
    if state and state['key'] == (draft['room_id'], draft['draft_id']):
        state.update(draft=draft, dirty=True)
        return
    p = draft_path(draft["room_id"], draft["draft_id"])
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def track_generated_asset(draft: dict[str, Any], asset_id: str) -> None:
    ids = draft.setdefault("generated_asset_ids", [])
    if asset_id not in ids:
        ids.append(asset_id)
    save_draft(draft)


def commit_draft(room_id: str, draft_id: str, validate, *, checkpoint=False) -> dict[str, Any]:
    """Validate then apply the draft to the live content with compare-and-swap.

    `validate` is a callable(sequence, room_id) -> list[str] of problems; commit
    is refused while any problem remains. Returns {ok, conflict, problems}.
    On success the draft file is marked committed (kept for audit/undo)."""
    draft = load_draft(room_id, draft_id)
    if draft.get('presentation_only'):
        return {'ok':False,'conflict':False,'problems':['別の見本を提示する作業から元タイムラインは変更できません']}
    problems = validate(draft["sequence"], room_id)
    if draft.get("base_sequence") is not None:
        from app.services.timeline_scope import violations
        problems += violations(draft["base_sequence"], draft["sequence"], draft.get("edit_scope"))
    if problems:
        return {"ok": False, "conflict": False, "problems": problems}
    with ContentsLock(room_id):
        if draft.get('job_id') and (_room_dir(room_id)/'jobs'/draft['job_id']/'cancel-requested').exists():
            return {"ok":False,"conflict":False,"problems":["制作はユーザーにより停止されました"]}
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
        fmt = draft['sequence'].get('format') or content['timeline'].get('format') or content.get('format')
        if fmt:
            content['timeline']['format'] = fmt
            content['format'] = fmt
        _write_contents_raw(room_id, contents)
    if checkpoint:
        draft['base_hash'] = sequence_hash(draft['sequence'])
        draft['published_sequence'] = json.loads(json.dumps(draft['sequence']))
        draft['published_at'] = time.time()
    else:
        draft["committed_at"] = time.time()
    save_draft(draft)
    return {"ok": True, "conflict": False, "problems": []}


def publish_checkpoint(room_id: str, draft_id: str) -> dict[str, Any]:
    """Publish one complete tool transaction, never its intermediate sub-operations.

    The original snapshot remains the authority for scope/approved clips. A manual
    save changes the CAS hash and stops publication rather than erasing that edit.
    """
    draft = load_draft(room_id, draft_id)
    if not draft.get('live_updates'):
        return {'ok': True, 'published': False}
    if sequence_hash(draft['sequence']) == draft['base_hash']:
        return {'ok': True, 'published': False}
    from app.services import timeline_commands as tc
    p = _room_dir(room_id) / 'assets.json'
    assets = {str(a['id']): a for a in json.loads(p.read_text(encoding='utf-8'))} if p.exists() else {}
    baseline = set(draft.get('baseline_problems', []))
    result = commit_draft(room_id, draft_id,
        lambda seq, room: [x for x in tc.validate_sequence(seq, assets, asset_dir=str(_room_dir(room))) if x not in baseline],
        checkpoint=True)
    return {**result, 'published': result['ok']}


def refresh_checkpoint(room_id: str, draft_id: str) -> bool:
    """Adopt a human save before the next AI operation when no unpublished edit exists."""
    draft = load_draft(room_id, draft_id)
    if not draft.get('live_updates'):
        return False
    with ContentsLock(room_id):
        content = _find_content(_read_contents_raw(room_id), draft['content_id'])
        live = _content_sequence(content) if content else None
        if live is None or sequence_hash(live) == draft['base_hash']:
            return False
        if sequence_hash(draft['sequence']) != draft['base_hash']:
            raise ValueError('手編集と未反映のAI編集が重なっています。最新のタイムラインと下書きを確認してください。')
        draft['sequence'] = json.loads(json.dumps(live))
        draft['base_sequence'] = json.loads(json.dumps(live))
        draft['base_hash'] = sequence_hash(live)
        draft['published_sequence'] = json.loads(json.dumps(live))
        save_draft(draft)
    return True


def discard_draft(room_id: str, draft_id: str, delete_generated_assets) -> None:
    """Drop the draft; garbage-collect assets that were generated for it.
    `delete_generated_assets` is a callable(room_id, list[str])."""
    try:
        draft = load_draft(room_id, draft_id)
    except ValueError:
        return
    gen = draft.get("generated_asset_ids") or []
    # Published checkpoints and native undo history may still reference these.
    if gen and not draft.get("committed_at") and not draft.get('published_at'):
        try:
            delete_generated_assets(room_id, gen)
        except Exception:  # noqa: BLE001 — GC must not mask the discard
            pass
    draft["discarded_at"] = time.time()
    save_draft(draft)
