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


_DOTENV_FLAG_CACHE: Optional[bool] = None
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _dotenv_streaming_flag() -> bool:
    """プロジェクト .env の DAN_STREAMING_INPUT を読む（プロセス環境に無い時の既定）。

    watchdog (dan_core_autostart.bat) 経由の自動再起動はユーザー環境変数を
    引き継がないため、環境変数だけに依存すると再起動のたびに追い連絡が
    黙ってOFFになる（2026-06-11 に実際に発生: OFF化で DAN_PARALLEL_SEND の
    時刻逆転パスが有効化し、表示順バグとして顕在化した）。
    """
    global _DOTENV_FLAG_CACHE
    if _DOTENV_FLAG_CACHE is None:
        value = ""
        try:
            from pathlib import Path
            env_path = Path(__file__).resolve().parents[2] / ".env"
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("DAN_STREAMING_INPUT="):
                    value = line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            value = ""
        _DOTENV_FLAG_CACHE = value.lower() in ("1", "true", "yes", "on")
    return _DOTENV_FLAG_CACHE


def streaming_enabled() -> bool:
    """True when the persistent streaming session path is opted in.

    プロセス環境変数が最優先（明示的な ON/OFF 切替用）。未設定なら .env を見る。
    """
    raw = os.environ.get("DAN_STREAMING_INPUT")
    if raw is not None and raw.strip() != "":
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return _dotenv_streaming_flag()


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
        # Receiver for CLI-INITIATED turns: the CLI fires a new model turn on its
        # own when a background task finishes while the session is idle (measured
        # and confirmed 2026-07-24 — same native wake as interactive Claude Code).
        # Without a sink those events were silently DROPPED, which is why Dan
        # stalled after "お待ちください". cli_runner installs a room-scoped sink
        # that classifies + persists these turns like any other.
        self.background_sink: Optional[EventSink] = None
        # True while a CLI-initiated (autonomous) turn is streaming.
        self._auto_active = False
        # Set True when the last run_turn ended because the CLI went silent for
        # longer than the idle timeout (a real hang), as opposed to finishing.
        self._last_turn_hung = False
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
        """True while a turn is in flight — including a CLI-initiated autonomous
        turn (background-completion wake). A new message then becomes a follow-up
        injected at the next step boundary, never a parallel send mid-turn."""
        return self.is_alive() and (self._turn is not None or self._auto_active)

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
                creationflags=_NO_WINDOW,
            )
            self._alive = True
            self._last_activity = time.time()
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()

    def stop(self) -> None:
        with self._lock:
            self._alive = False
            self._auto_active = False
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
            if self._running or self._auto_active:
                # A loop is already driving the CLI (user turn) OR the CLI is
                # mid-autonomous-turn. Submitting another user message now would
                # desynchronise the stream — route as a follow-up instead; the
                # boundary-interrupt logic applies it cleanly.
                self._pending.put(content)
                self._last_activity = time.time()
                return None
            self._running = True

        self._last_turn_hung = False
        # Cancel armed BEFORE the turn started (user hit cancel in the gap
        # between send and run start): abort without ever submitting the message.
        if self._consume_cancel_next():
            with self._lock:
                self._running = False
            return {"type": "result", "subtype": "cancelled_before_start", "is_error": False}
        hung = False
        # Re-check often enough to notice a hang promptly even for small idle
        # thresholds, but no more than the normal poll cadence.
        poll = max(0.2, min(_RUN_TURN_POLL_SECONDS, timeout / 2.0))
        try:
            turn = _Turn(sink=sink)
            self._turn = turn
            self._interrupt_sent = False
            self._last_activity = time.time()
            # 送信直前の再確認: キャンセルが「入口チェック通過後〜ここまで」の
            # 隙間（文脈再構築などで数百msある）に届いた場合もここで拾う。
            # ターミナルのEscに効き漏れが無いのと同じ保証にするための二重化。
            if self._consume_cancel_next():
                self._turn = None
                return {"type": "result", "subtype": "cancelled_before_start", "is_error": False}
            self._send_user(content)
            # 送信直後の再確認: kill_cli_process が「実行中ターン無し」と判定して
            # 旗を武装した直後にこの送信が走った場合（最後の隙間）は、始まった
            # ばかりのターンへ即座に割り込みを送って畳む。_interrupt_sent は
            # 触らない（あれは追い連絡の境界マーカー。立てると完了イベントが
            # 出なくなり、ライブ表示が畳まれない）。
            if self._consume_cancel_next():
                try:
                    self._send_interrupt()
                except Exception:
                    pass

            # Keep running follow-up turns until nothing is pending.
            last_result: Optional[TurnEvent] = None
            while True:
                if turn.done.wait(timeout=poll):
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
            if hung:
                # Drop the poisoned/half-finished process; the next turn will
                # start a fresh CLI via start() in run_turn/get_or_create_session.
                self.stop()

    def submit_followup(self, content: str) -> None:
        """Queue a follow-up. If a turn is in flight it will be applied at the
        next step boundary (interrupt → next turn); otherwise it is picked up
        as the next turn."""
        self._pending.put(content)
        self._last_activity = time.time()

    # --- user cancel (Escキー相当) --------------------------------------
    def interrupt(self) -> bool:
        """Gracefully stop the CURRENT turn (the CLI ends it with a result
        event, exactly like pressing Esc in interactive Claude Code). The
        persistent process survives — killing it mid-turn is what desynchronised
        the stream and caused the `<invoke>` text leak.

        A very early interrupt (~0.1s after send) can be SWALLOWED: the CLI has
        nothing in flight yet, consumes the control request as a no-op, then
        starts the model call anyway (measured 2026-07-24 — the one timing where
        a cancelled question still got answered). So after the first interrupt a
        nudger re-sends it every 1.2s while THIS SAME turn is still alive (max
        3 nudges). Identity-guarded: the moment the turn ends or a new turn
        starts, nudging stops — a follow-up message can never be hit."""
        if not self.is_turn_active():
            return False
        target = self._turn

        def _nudge() -> None:
            for _ in range(3):
                time.sleep(1.2)
                if target is None or self._turn is not target or not self.is_alive():
                    return
                try:
                    self._send_interrupt()
                except Exception:
                    return

        try:
            self._send_interrupt()
            if target is not None:
                threading.Thread(target=_nudge, daemon=True).start()
            return True
        except Exception:
            return False

    def cancel_next_turn(self, ttl: float = 3.0) -> None:
        """Arm a short-lived cancel for a turn that has NOT started yet. Covers
        the race where the user hits cancel after sending but before the run
        spins up — without this the late-starting turn ignored the cancel and
        "走り出す". run_turn checks the flag at entry and aborts.

        TTL は3秒: 送信→キャンセルのレース窓を覆うのに十分で、かつ「何もない時の
        キャンセル連打が地雷として残り、直後の正当な送信を闇討ちする」誤爆窓
        （2026-07-24 実測10秒で発生）を最小化する。"""
        self._cancel_next_until = time.time() + ttl

    def _consume_cancel_next(self) -> bool:
        until = getattr(self, "_cancel_next_until", 0.0)
        if until and time.time() < until:
            self._cancel_next_until = 0.0
            return True
        return False

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

        # --- CLI-initiated (autonomous) turn: no run_turn loop is waiting. ---
        # The CLI woke itself (a background task finished while idle). Route the
        # whole turn to the room's background sink so it is classified, saved
        # and rendered like any other turn instead of being dropped.
        if turn is None:
            if typ == "assistant" and not self._auto_active:
                self._auto_active = True
            if not self._auto_active:
                return  # stray system chatter between turns — nothing to do
            if typ == "user" and not self._interrupt_sent and not self._pending.empty():
                # a user message arrived mid-autonomous-turn: cut at this clean
                # boundary so their message is applied next, same as follow-ups
                self._interrupt_sent = True
                try:
                    self._send_interrupt()
                except Exception:
                    pass
            sink = self.background_sink
            if sink:
                try:
                    sink(ev)
                except Exception:
                    pass
            if typ == "result":
                self._auto_active = False
                self._interrupt_sent = False
                follow = self._drain_pending()
                if follow is not None:
                    # queued user messages continue as the next turn; its events
                    # flow through the same background sink (saved + rendered)
                    try:
                        self._send_user(follow)
                        self._auto_active = True
                    except Exception:
                        pass
            return

        # Step boundary = a tool result came back (`user` event). If a
        # follow-up is pending, interrupt now so it's applied at this clean
        # boundary instead of after the whole turn.
        if typ == "user" and not self._interrupt_sent and not self._pending.empty():
            self._interrupt_sent = True
            try:
                self._send_interrupt()
            except Exception:
                pass

        if turn.sink:
            try:
                turn.sink(ev)
            except Exception:
                pass

        if typ == "result":
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
