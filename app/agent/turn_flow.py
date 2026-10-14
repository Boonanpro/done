"""A message arrives while Dan is working in the room: what happens to it, and where the record of the work so far goes.

One place for every engine (the CLI a room's model runs on). The rules themselves are in
docs/current/chat-timeline-definition.md. An engine differs only in what ENGINES lists, and
tests/test_turn_flow_engines.py runs every rule on every engine listed there.

2026-10-14: the rules lived inside the Claude path only. In a room on GPT the record of an interrupted turn was placed
when it was saved, below the follow-up (the owner saw two messages in a row), and a follow-up sent in the first two
minutes of a turn was parked where nothing read it."""
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

# reads_mid_turn: a message that arrives while a turn runs can be handed to that turn, which reads it at its next step
# and goes on. False: the engine takes its input once per turn, so the running turn is stopped and a new one starts.
ENGINES: Dict[str, Dict[str, bool]] = {
    "claude": {"reads_mid_turn": True},
    "codex": {"reads_mid_turn": False},
}


def engine_of(saved_model: Optional[str] = None) -> str:
    """The engine a room runs on, from the model saved for it (projects.metadata.model; none = the default model)."""
    from app.agent import cli_runner as cr
    model = (saved_model or "").strip().lower()
    if model not in cr._ALLOWED_CLI_MODELS:
        model = cr._resolve_cli_model_raw(None)
    return cr._codex.backend_for_model(model)


def reads_mid_turn(engine: str) -> bool:
    if not ENGINES[engine]["reads_mid_turn"]:
        return False
    from app.agent.streaming_session import streaming_enabled
    return streaming_enabled()   # off: this engine too runs one process per turn


def waits_for_running_turn(room_id: str, engine: str) -> bool:
    """The message is handed to the turn that is running or being prepared, and no new turn starts for it.
    Never for an engine that cannot read mid-turn: nothing there would take the message out again."""
    if not reads_mid_turn(engine):
        return False
    from app.agent.streaming_session import is_turn_active_or_preparing
    return is_turn_active_or_preparing(room_id)


def claim_new_turn(room_id: str, engine: str) -> Optional[object]:
    """Mark the room as preparing a turn, so a message in the next seconds waits for that turn. Only where the turn
    will read it; the mark is taken off when the turn writes its first words (streaming_session.run_turn)."""
    if not reads_mid_turn(engine):
        return None
    from app.agent.streaming_session import claim_turn
    return claim_turn(room_id)


def release_claim(room_id: str, token: Optional[object]) -> None:
    if token is not None:
        from app.agent.streaming_session import release_turn_claim
        release_turn_claim(room_id, token)


_lock = threading.Lock()
_stopped: Dict[str, Tuple[str, float]] = {}   # run id -> (when the message that stopped it was received, when noted)
_KEEP_SECONDS = 3600.0   # a stopped turn saves within seconds; one that saved nothing leaves its note until then


def stopped_by_message(run_id: Optional[str], received_at: Optional[str]) -> None:
    """A message stopped this run's turn (the engine could not hand it over). The turn's record is saved a moment
    later by its own thread, which asks record_time. received_at: the message's saved time (none yet = now)."""
    if not run_id:
        return
    received_at = received_at or datetime.now(timezone.utc).isoformat()
    now = time.time()
    with _lock:
        for old in [r for r, (_, noted) in _stopped.items() if now - noted > _KEEP_SECONDS]:
            _stopped.pop(old, None)
        _stopped.setdefault(run_id, (str(received_at), now))


def record_time(run_id: Optional[str], handed_over_at: Optional[str] = None) -> Optional[str]:
    """The created_at for the record of a turn that has just ended, on any engine.

    A turn a message cut into holds work done before that message, so its record goes just before the message (below the
    message it answers, above the one that cut in). handed_over_at: when the cutting message was received, for a turn that
    read it mid-turn. Otherwise the note left by stopped_by_message is used, once. None = not cut into: placed when saved."""
    with _lock:
        noted = _stopped.pop(run_id, None) if run_id else None
    at = handed_over_at or (noted[0] if noted else None)
    if not at:
        return None
    from app.agent.cli_runner import _just_before_iso
    return _just_before_iso(at)
