# -*- coding: utf-8 -*-
"""Persistent Claude Code streaming session (per room).

Flag-gated foundation for "follow up while Dan is working" (B-approach).
Instead of spawning a fresh one-shot `claude` process per turn, we keep ONE
`claude --input-format stream-json` process alive per room. Follow-up messages
sent while a turn is running are not lost and not ignored until the whole turn
finishes — they are applied at the **next step boundary**:

  * a follow-up is queued as "pending";
  * the reader watches the output stream; when the current step finishes
    (a tool result comes back, i.e. a `user` event), if something is pending
    it sends an interrupt control message, ending the current turn cleanly at
    that boundary;
  * the pending follow-up (plus a short note of what Dan was doing) is then
    submitted as the next turn, so Dan re-judges with the new info.

This module is intentionally self-contained and import-safe; nothing here runs
unless callers opt in (the chat flow only uses it when DAN_STREAMING_INPUT is
truthy). It is unit-testable on its own via run_turn()/submit_followup().

NOTE: This is step 1 (the session manager). Wiring it into the SSE chat flow
is a later step.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional


def streaming_enabled() -> bool:
    """True when the persistent streaming session path is opted in."""
    return os.environ.get("DAN_STREAMING_INPUT", "").lower() in ("1", "true", "yes", "on")


# How often run_turn wakes to re-check idle/liveness while waiting on a turn.
# An actively streaming turn sets done quickly; this only bounds how fast we
# notice a real hang or a freshly arrived result.
_RUN_TURN_POLL_SECONDS = 2.0


TurnEvent = dict  # parsed JSON object from the CLI stream
EventSink = Callable[[TurnEvent], None]


@dataclass
class _Turn:
    """One in-flight turn: collects events and signals completion."""
    sink: Optional[EventSink] = None
    done: threading.Event = field(default_factory=threading.Event)
    result: Optional[TurnEvent] = None
    saw_step_boundary: bool = False


class StreamingSession:
    """A long-lived `claude` stream-json process for one room."""

    def __init__(
        self,
        room_id: str,
        build_cmd: Callable[[], list],
        env: Dict[str, str],
        cwd: str,
        idle_timeout: float = 600.0,
    ):
        self.room_id = room_id
        self._build_cmd = build_cmd
        self._env = env
        self._cwd = cwd
        self.idle_timeout = idle_timeout

        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._reader: Optional[threading.Thread] = None
        self._alive = False
        self._last_activity = time.time()

        # Current turn + a queue of pending follow-up texts.
        self._turn: Optional[_Turn] = None
        self._pending: "queue.Queue[str]" = queue.Queue()
        self._interrupt_sent = False
        # Set True when the last run_turn ended because the CLI went silent for
        # longer than the idle timeout (a real hang), as opposed to finishing.
        self._last_turn_hung = False
        # True while a run_turn loop is active. Guards against a second,
        # concurrent run_turn on the same session (e.g. a follow-up request that
        # raced is_turn_active and fell through to a fresh process_message_cli):
        # such a call must NOT start a parallel loop (that double-processes the
        # CLI output and double-saves) — it is routed as a follow-up instead.
        self._running = False
        # Set by cancel() (user pressed stop): the active turn should stop ASAP.
        # run_turn checks this each poll, breaks, and returns so the caller can
        # persist any partial output and tear the session down — so a resend
        # starts a FRESH run instead of being mis-routed as a follow-up to a
        # still-"active" session.
        self._cancelled = threading.Event()
        self._last_turn_cancelled = False
        # Set by cancel(rollback=True): the cancel happened before Dan produced
        # any output, so the caller will delete the run/events/message entirely
        # ("as if never sent"). The sink must then SKIP its own DB writes so it
        # doesn't re-create the rows the endpoint is deleting.
        self._rollback = False

    # --- lifecycle ------------------------------------------------------
    def is_alive(self) -> bool:
        return self._alive and self._proc is not None and self._proc.poll() is None

    def is_turn_active(self) -> bool:
        """True while a turn is in flight (so a new message should be treated as
        a follow-up to inject at the next step boundary, not a fresh run)."""
        return self.is_alive() and self._turn is not None

    def start(self) -> None:
        with self._lock:
            if self.is_alive():
                return
            cmd = self._build_cmd()
            self._proc = subprocess.Popen(
                cmd,
                cwd=self._cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self._env,
                bufsize=1,
            )
            self._alive = True
            self._last_activity = time.time()
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()

    def stop(self) -> None:
        with self._lock:
            self._alive = False
            proc = self._proc
            self._proc = None
        if proc:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def idle_seconds(self) -> float:
        return time.time() - self._last_activity

    # --- writing to the CLI --------------------------------------------
    def _write(self, obj: dict) -> None:
        proc = self._proc
        if not proc or not proc.stdin:
            raise RuntimeError("streaming session not started")
        proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    def _send_user(self, text: str) -> None:
        self._write({"type": "user", "message": {"role": "user", "content": text}})

    def _send_interrupt(self) -> None:
        self._write({
            "type": "control_request",
            "request_id": f"int-{uuid.uuid4().hex[:8]}",
            "request": {"subtype": "interrupt"},
        })

    # --- public turn API -----------------------------------------------
    @property
    def last_turn_hung(self) -> bool:
        """True if the most recent run_turn ended on an idle hang (not a clean
        result). The caller uses this to persist partial output and warn the
        user instead of closing the stream on silence."""
        return self._last_turn_hung

    def run_turn(self, content: str, sink: EventSink, timeout: float = 600.0) -> Optional[TurnEvent]:
        """Submit a user message and stream this turn's events to `sink`.

        `timeout` is the maximum *idle* gap — seconds with NO output at all from
        the CLI — not a cap on total turn duration. A turn that keeps streaming
        (tool calls, text, thinking) is never abandoned, no matter how long it
        runs; only a turn that goes completely silent for `timeout` seconds is
        treated as a hang. This is the whole point of the streaming path: long
        tasks ("時間をかけて品質優先で") must run to completion and still deliver
        their answer rather than being cut off at a fixed wall-clock limit.

        On a genuine idle hang the session is torn down (the CLI process is
        stopped) so the NEXT turn starts on a clean process. A half-finished
        turn left inside the persistent process desynchronises the stream and
        makes the model emit its tool calls as plain text (the `<invoke …>`
        leak), which then repeats on every later turn — resetting the process
        is what prevents that loop.

        Returns the final `result` event, or None on an idle hang (in which case
        `last_turn_hung` is True). Follow-ups submitted via submit_followup()
        during the turn are applied at the next step boundary and produce
        subsequent turns through the same sink."""
        if not self.is_alive():
            self.start()

        # Serialize: only ONE run_turn loop may be active per session. A second,
        # concurrent call (e.g. a follow-up request that raced is_turn_active and
        # fell through to a fresh process_message_cli) must NOT spin a parallel
        # loop driving the same CLI process — that double-processes the output
        # and double-saves the answer. Route its content as a follow-up to the
        # active loop and return immediately.
        with self._lock:
            if self._running:
                self._pending.put(content)
                self._last_activity = time.time()
                return None
            self._running = True
            # Fresh turn → no cancel pending yet. (Cancel tears the session down,
            # so this is normally a brand-new object; clearing is belt-and-braces.)
            self._cancelled.clear()

        self._last_turn_hung = False
        hung = False
        cancelled = False
        # Re-check often enough to notice a hang promptly even for small idle
        # thresholds, but no more than the normal poll cadence.
        poll = max(0.2, min(_RUN_TURN_POLL_SECONDS, timeout / 2.0))
        try:
            turn = _Turn(sink=sink)
            self._turn = turn
            self._interrupt_sent = False
            self._last_activity = time.time()
            self._send_user(content)

            # Keep running follow-up turns until nothing is pending.
            last_result: Optional[TurnEvent] = None
            while True:
                # User pressed stop: abandon this turn now (partial output is
                # already in the sink; the caller persists it and tears down).
                if self._cancelled.is_set():
                    cancelled = True
                    break
                if turn.done.wait(timeout=poll):
                    if self._cancelled.is_set():
                        cancelled = True
                        break
                    last_result = turn.result
                    # If a follow-up was queued, start the next turn for it.
                    follow = self._drain_pending()
                    if follow is None:
                        break
                    turn = _Turn(sink=sink)
                    self._turn = turn
                    self._interrupt_sent = False
                    self._last_activity = time.time()
                    self._send_user(follow)
                    continue
                # Not done yet — give up only if the CLI died or has gone silent
                # for longer than the idle timeout. An active turn keeps
                # _last_activity fresh (updated per CLI line in _read_loop), so
                # this never fires while output is still flowing.
                if not self.is_alive():
                    break
                if time.time() - self._last_activity > timeout:
                    hung = True
                    break
            return last_result
        finally:
            self._turn = None
            self._running = False
            self._last_turn_hung = hung
            self._last_turn_cancelled = cancelled
            if hung:
                # Drop the poisoned/half-finished process; the next turn will
                # start a fresh CLI via start() in run_turn/get_or_create_session.
                self.stop()

    @property
    def last_turn_cancelled(self) -> bool:
        """True if the most recent run_turn ended because cancel() was called
        (user pressed stop), as opposed to finishing or hanging."""
        return self._last_turn_cancelled

    @property
    def rollback_requested(self) -> bool:
        """True when the active turn was cancelled before any output and should be
        fully rolled back (the sink skips its DB writes; the endpoint deletes the
        run/events/message)."""
        return self._rollback

    def cancel(self, rollback: bool = False) -> None:
        """Stop the in-flight turn now (user pressed stop). Signals run_turn to
        break, nudges the CLI to stop generating, and tears the process down
        synchronously so is_turn_active() flips False right away — a fast resend
        then starts a fresh run instead of being mis-routed as a follow-up to a
        still-"active" session.

        rollback=True: the cancel landed before Dan produced output, so the sink
        must skip persisting anything (the caller deletes the run/message)."""
        self._rollback = rollback
        self._cancelled.set()
        # Nudge the CLI to stop emitting tokens for the current turn.
        if self.is_alive() and self._turn is not None:
            try:
                self._send_interrupt()
            except Exception:
                pass
        # Unblock the run_turn poll immediately.
        t = self._turn
        if t and not t.done.is_set():
            t.done.set()
        # Tear the process down so a resend isn't classified as a follow-up.
        self.stop()

    def submit_followup(self, content: str) -> None:
        """Queue a follow-up. If a turn is in flight it will be applied at the
        next step boundary (interrupt → next turn); otherwise it is picked up
        as the next turn."""
        self._pending.put(content)
        self._last_activity = time.time()

    def _drain_pending(self) -> Optional[str]:
        texts = []
        while True:
            try:
                texts.append(self._pending.get_nowait())
            except queue.Empty:
                break
        if not texts:
            return None
        if len(texts) == 1:
            return texts[0]
        # Multiple stacked follow-ups → combine in order.
        return "\n".join(f"- {t}" for t in texts)

    # --- reader loop ----------------------------------------------------
    def _read_loop(self) -> None:
        proc = self._proc
        if not proc or not proc.stdout:
            return
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                self._last_activity = time.time()
                self._dispatch(ev)
        except Exception:
            pass
        finally:
            self._alive = False
            # Unblock any waiter.
            t = self._turn
            if t and not t.done.is_set():
                t.done.set()

    def _dispatch(self, ev: TurnEvent) -> None:
        typ = ev.get("type")
        turn = self._turn

        # Step boundary = a tool result came back (`user` event). If a
        # follow-up is pending, interrupt now so it's applied at this clean
        # boundary instead of after the whole turn.
        if typ == "user" and turn and not self._interrupt_sent and not self._pending.empty():
            self._interrupt_sent = True
            try:
                self._send_interrupt()
            except Exception:
                pass

        if turn and turn.sink:
            try:
                turn.sink(ev)
            except Exception:
                pass

        if typ == "result" and turn:
            turn.result = ev
            turn.done.set()


# --- registry -----------------------------------------------------------
_sessions: Dict[str, StreamingSession] = {}
_registry_lock = threading.Lock()


def get_session(room_id: str) -> Optional[StreamingSession]:
    with _registry_lock:
        s = _sessions.get(room_id)
        if s and not s.is_alive():
            _sessions.pop(room_id, None)
            return None
        return s


def get_or_create_session(
    room_id: str,
    build_cmd: Callable[[], list],
    env: Dict[str, str],
    cwd: str,
) -> StreamingSession:
    with _registry_lock:
        s = _sessions.get(room_id)
        if s and s.is_alive():
            return s
        s = StreamingSession(room_id, build_cmd, env, cwd)
        _sessions[room_id] = s
    s.start()
    return s


def has_active_session(room_id: str) -> bool:
    s = get_session(room_id)
    return bool(s and s.is_alive())


def cancel_session(room_id: str, rollback: bool = False) -> bool:
    """Cancel a room's in-flight turn (user pressed stop) and drop the session
    from the registry so the next message starts a fresh run. Returns True if a
    session existed. Without this, the persistent streaming session is never
    stopped on cancel (kill_cli_process only knows the one-shot registry), so
    is_turn_active() stays True and a resend is mis-routed as a follow-up.

    rollback=True signals a "before output" cancel: the sink skips its DB writes
    so the caller can delete the run/events/message cleanly (CLI-like rollback)."""
    with _registry_lock:
        s = _sessions.get(room_id)
    if s is None:
        return False
    try:
        s.cancel(rollback=rollback)
    finally:
        with _registry_lock:
            if _sessions.get(room_id) is s:
                _sessions.pop(room_id, None)
    return True
