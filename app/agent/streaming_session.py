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
        # True while a run_turn loop is active. Guards against a second,
        # concurrent run_turn on the same session (e.g. a follow-up request that
        # raced is_turn_active and fell through to a fresh process_message_cli):
        # such a call must NOT start a parallel loop (that double-processes the
        # CLI output and double-saves) — it is routed as a follow-up instead.
        self._running = False

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
    def run_turn(self, content: str, sink: EventSink, timeout: float = 600.0) -> Optional[TurnEvent]:
        """Submit a user message and stream this turn's events to `sink`.
        Blocks until the turn's `result` arrives (or timeout). Returns the
        result event. Follow-ups submitted via submit_followup() during the
        turn are applied at the next step boundary and produce subsequent
        turns (each re-invokes run_turn-like streaming through the same sink)."""
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

        try:
            turn = _Turn(sink=sink)
            self._turn = turn
            self._interrupt_sent = False
            self._last_activity = time.time()
            self._send_user(content)

            # Keep running follow-up turns until nothing is pending.
            last_result: Optional[TurnEvent] = None
            deadline = time.time() + timeout
            while True:
                if not turn.done.wait(timeout=max(0.5, deadline - time.time())):
                    break  # timeout
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
                deadline = time.time() + timeout
            return last_result
        finally:
            self._turn = None
            self._running = False

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
