"""The models the owner can pick, read from what the providers say is available now.

Nothing here is a hand-kept list that goes stale when a model ships (2026-10-27: GPT-6.1 Sol/Terra
were usable in Codex for days while the picker still offered GPT-5.6).

* GPT (Codex CLI, ChatGPT sign-in): Codex keeps the models of our sign-in in
  ``$CODEX_HOME/models_cache.json`` and refreshes it itself whenever it starts. ``visibility: list``
  entries are the ones offered. A slug is ``gpt-<version>-<tier>``; the newest version of each tier
  is offered, and a room saved on an older version of a tier runs on the newest one (the same way the
  Claude aliases move to the newest model), so a new release reaches every room and job at once.
* Claude (Claude CLI, Max plan): the aliases ``opus`` / ``sonnet`` / ``fable`` / ``haiku`` always run
  the newest model of their family, so a room needs no change. Anthropic's ``/v1/models`` tells which
  version that is (for the label) and shows a family that has no alias yet (offered by its full id).
  It is read in the background at most every few hours; the last answer is kept on disk.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CODEX_HOME = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
_CLAUDE_STORE = _PROJECT_ROOT / ".data" / "model_catalog" / "claude.json"
_CLAUDE_REFRESH_SECONDS = 6 * 3600
_CLAUDE_RETRY_SECONDS = 15 * 60

CLAUDE_ALIASES = ("fable", "opus", "sonnet", "haiku")
CLAUDE_OFFERED = ("fable", "opus", "sonnet")            # haiku runs, but is not offered in the picker
_CLAUDE_FALLBACK_LABELS = {"fable": "Claude Fable 5.1", "opus": "Claude Opus", "sonnet": "Claude Sonnet", "haiku": "Claude Haiku"}

# Used only when Codex has never written its model list on this machine.
_CODEX_FALLBACK = [
    {"slug": "gpt-6-astra", "display_name": "GPT-6-Astra", "visibility": "list", "priority": 1},
    {"slug": "gpt-5.6-sol", "display_name": "GPT-5.6-Sol", "visibility": "list", "priority": 2},
    {"slug": "gpt-5.6-terra", "display_name": "GPT-5.6-Terra", "visibility": "list", "priority": 3},
    {"slug": "gpt-5.6-luna", "display_name": "GPT-5.6-Luna", "visibility": "list", "priority": 4},
    {"slug": "gpt-5.5", "display_name": "GPT-5.5", "visibility": "hide", "priority": 5},
]

_GPT = re.compile(r"^gpt-(\d+(?:\.\d+)*)(?:-([a-z]+))?$")
_GPT_SAFE = re.compile(r"^gpt-\d[a-z0-9.\-]*$")
_CLAUDE_ID = re.compile(r"^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?$")


def _norm(model: Optional[str]) -> str:
    return (model or "").strip().lower()


# ---------------------------------------------------------------------------
# GPT (Codex)
# ---------------------------------------------------------------------------

_codex_lock = threading.Lock()
_codex_cached: tuple[float, list[dict[str, Any]]] = (-1.0, [])


def _codex_models() -> list[dict[str, Any]]:
    """Codex's model list for our sign-in (re-read only when the file changes)."""
    global _codex_cached
    path = _CODEX_HOME / "models_cache.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return list(_CODEX_FALLBACK)
    with _codex_lock:
        if _codex_cached[0] == mtime:
            return _codex_cached[1]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            raw = data.get("models") if isinstance(data, dict) else data
            models = [
                {"slug": _norm(m.get("slug")), "display_name": m.get("display_name") or m.get("slug"),
                 "visibility": m.get("visibility") or "list",
                 "priority": m.get("priority") if isinstance(m.get("priority"), (int, float)) else 999}
                for m in (raw or []) if isinstance(m, dict) and _GPT_SAFE.match(_norm(m.get("slug")))
            ]
        except Exception as e:  # noqa: BLE001
            logger.warning("codex models_cache unreadable: %s", e)
            models = []
        if not models:
            models = list(_CODEX_FALLBACK)
        _codex_cached = (mtime, models)
        return models


def _gpt_parts(slug: str) -> Optional[tuple[str, tuple[int, ...]]]:
    m = _GPT.match(slug)
    if not m:
        return None
    return (m.group(2) or "", tuple(int(x) for x in m.group(1).split(".")))


def _gpt_label(display_name: str) -> str:
    return re.sub(r"^GPT-([\d.]+)[- ]+", r"GPT-\1 ", str(display_name).strip())


def is_codex_model(model: Optional[str]) -> bool:
    """A model that runs through Codex (any ``gpt-*`` name)."""
    return bool(_GPT_SAFE.match(_norm(model)))


def known_codex_models() -> set[str]:
    return {m["slug"] for m in _codex_models()} | {m["slug"] for m in _CODEX_FALLBACK}


def current(model: Optional[str]) -> str:
    """The model a saved choice runs on now: the newest offered version of the same GPT tier
    (``gpt-6-astra`` → ``gpt-6.1-astra`` once Codex offers it). Claude names are returned as they are
    (their aliases already follow the newest model)."""
    m = _norm(model)
    parts = _gpt_parts(m)
    if not parts:
        return m
    tier, version = parts
    best: Optional[tuple[tuple[int, ...], str]] = None
    for entry in _codex_models():
        if entry["visibility"] != "list":
            continue
        p = _gpt_parts(entry["slug"])
        if p and p[0] == tier and p[1] > version and (best is None or p[1] > best[0]):
            best = (p[1], entry["slug"])
    return best[1] if best else m


def codex_options() -> list[dict[str, str]]:
    """The newest offered version of each GPT tier, in Codex's order."""
    newest: dict[str, tuple[tuple[int, ...], dict[str, Any]]] = {}
    for entry in _codex_models():
        if entry["visibility"] != "list":
            continue
        p = _gpt_parts(entry["slug"])
        key = p[0] if p else entry["slug"]
        version = p[1] if p else ()
        if key not in newest or version > newest[key][0]:
            newest[key] = (version, entry)
    chosen = sorted((e for _, e in newest.values()), key=lambda e: e["priority"])
    return [{"id": e["slug"], "label": _gpt_label(e["display_name"]), "backend": "codex"} for e in chosen]


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------

_claude_lock = threading.Lock()
_claude_state: dict[str, Any] = {"loaded": False, "data": None, "next_try": 0.0, "running": False}


def _anthropic_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY") or ""
    if key:
        return key.strip()
    try:
        for line in (_PROJECT_ROOT / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _fetch_claude_models() -> list[dict[str, Any]]:
    """Anthropic's model list (listing models costs nothing)."""
    key = _anthropic_key()
    if not key:
        raise RuntimeError("no Anthropic key")
    found: list[dict[str, Any]] = []
    after = ""
    for _ in range(10):
        url = "https://api.anthropic.com/v1/models?limit=100" + (f"&after_id={after}" if after else "")
        req = urllib.request.Request(url, headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            page = json.loads(resp.read().decode("utf-8"))
        found += [m for m in page.get("data") or [] if isinstance(m, dict)]
        if not page.get("has_more") or not page.get("last_id"):
            break
        after = page["last_id"]
    return found


def newest_claude_families(models: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """family → {id, label} of its newest model."""
    best: dict[str, tuple[tuple[int, int], str, dict[str, str]]] = {}
    for m in models:
        mid = _norm(m.get("id"))
        hit = _CLAUDE_ID.match(mid)
        if not hit:
            continue
        family = hit.group(1)
        version = (int(hit.group(2)), int(hit.group(3) or 0))
        created = str(m.get("created_at") or "")
        entry = {"id": mid, "label": str(m.get("display_name") or mid)}
        if family not in best or (version, created) > (best[family][0], best[family][1]):
            best[family] = (version, created, entry)
    return {f: v[2] for f, v in best.items()}


def _refresh_claude() -> None:
    try:
        families = newest_claude_families(_fetch_claude_models())
        if not families:
            raise RuntimeError("empty model list")
        data = {"checked_at": time.time(), "families": families}
        _CLAUDE_STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CLAUDE_STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(_CLAUDE_STORE)
        with _claude_lock:
            before = (_claude_state["data"] or {}).get("families") or {}
            _claude_state.update(data=data, next_try=time.time() + _CLAUDE_REFRESH_SECONDS)
        added = {f: v["id"] for f, v in families.items() if (before.get(f) or {}).get("id") != v["id"]}
        if added and before:
            logger.info("[MODELS] new Claude models: %s", added)
    except Exception as e:  # noqa: BLE001
        logger.info("[MODELS] Claude model list not read: %s", e)
        with _claude_lock:
            _claude_state["next_try"] = time.time() + _CLAUDE_RETRY_SECONDS
    finally:
        with _claude_lock:
            _claude_state["running"] = False


def _claude_families(wait: bool = False) -> dict[str, dict[str, str]]:
    """The last known newest model of each Claude family; starts a background re-read when it is old."""
    start = False
    with _claude_lock:
        if not _claude_state["loaded"]:
            _claude_state["loaded"] = True
            try:
                saved = json.loads(_CLAUDE_STORE.read_text(encoding="utf-8"))
                _claude_state["data"] = saved
                _claude_state["next_try"] = float(saved.get("checked_at") or 0) + _CLAUDE_REFRESH_SECONDS
            except Exception:  # noqa: BLE001
                pass
        if not _claude_state["running"] and time.time() >= _claude_state["next_try"]:
            _claude_state["running"] = True
            start = True
    if start:
        if wait:
            _refresh_claude()
        else:
            threading.Thread(target=_refresh_claude, name="model-catalog-claude", daemon=True).start()
    with _claude_lock:
        return dict(((_claude_state["data"] or {}).get("families")) or {})


def known_claude_models() -> set[str]:
    """Aliases plus the full id of each family's newest model (a family without an alias runs by its id)."""
    return set(CLAUDE_ALIASES) | {v["id"] for v in _claude_families().values()}


def claude_options() -> list[dict[str, str]]:
    families = _claude_families()
    options = [
        {"id": alias, "label": (families.get(alias) or {}).get("label") or _CLAUDE_FALLBACK_LABELS[alias], "backend": "claude"}
        for alias in CLAUDE_OFFERED
    ]
    for family, entry in families.items():
        if family not in CLAUDE_ALIASES:
            options.append({"id": entry["id"], "label": entry["label"], "backend": "claude"})
    return options


# ---------------------------------------------------------------------------
# Together
# ---------------------------------------------------------------------------

def options() -> list[dict[str, str]]:
    """Everything the room / dev-room model pickers offer, newest models included."""
    return claude_options() + codex_options()


def is_allowed(model: Optional[str]) -> bool:
    m = _norm(model)
    return bool(m) and (m in known_claude_models() or m in known_codex_models())


def label(model: Optional[str]) -> str:
    m = current(model)
    for o in options():
        if o["id"] == m:
            return o["label"]
    for e in _codex_models():
        if e["slug"] == m:
            return _gpt_label(e["display_name"])
    return m


class AllowedModels:
    """``model in _ALLOWED_CLI_MODELS`` keeps working, answered from the live lists."""

    def __contains__(self, model: object) -> bool:
        return isinstance(model, str) and is_allowed(model)

    def __iter__(self):
        return iter(sorted(known_claude_models() | known_codex_models()))


class LiveOptions:
    """A list-like view of :func:`options` (read fresh every time it is used)."""

    def __iter__(self):
        return iter(options())

    def __len__(self) -> int:
        return len(options())

    def __getitem__(self, index):
        return options()[index]
