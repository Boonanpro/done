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
from typing import Callable, Dict, Optional, Tuple

from app.agent import cli_record as _cli_record


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

# 担当（CLI）が道具の結果をモデルへ返した後、次の一手が来ないまま黙っていられる上限（秒）。
# モデルの返事待ちで10分以上黙るのは、API への接続が切れたまま戻らない固まり方
# （2026-10-29 X顧問の部屋: 14:41 から 38 分、通信は CLOSED のまま）。
# 道具の実行中（ffmpeg・Whisper・長い検索）は何分でも黙りうるので、そちらは run_turn の
# timeout（既定30分）で見る。
_MODEL_SILENCE_TIMEOUT = float(os.getenv("DAN_STREAMING_MODEL_SILENCE_TIMEOUT", "600"))
# 担当が自分で始めたターン（裏の作業が終わって起きた分）の見切り（2026-10-30）。
# run_turn の輪が無いので、沈黙の見張りは専用の糸で行う。
#   _AUTO_INTERRUPT_GRACE: 本人の言葉で割り込みを送ったのに result が来ない時、
#       これだけ黙ったら「ターンは終わっている」と見なして、待たせていた言葉を送る。
#   _AUTO_TURN_SILENCE_TIMEOUT: 道具の実行中でもこれ以上黙れば固まりとみなす。
_AUTO_INTERRUPT_GRACE = float(os.getenv("DAN_STREAMING_AUTO_INTERRUPT_GRACE", "20"))
_AUTO_TURN_SILENCE_TIMEOUT = float(os.getenv("DAN_STREAMING_AUTO_TURN_SILENCE_TIMEOUT", "1800"))
_AUTO_WATCH_POLL = 2.0


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
        self.model: Optional[str] = None
        self._build_cmd = build_cmd
        self._env = env
        self._cwd = cwd
        self.idle_timeout = idle_timeout

        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._reader: Optional[threading.Thread] = None
        self._alive = False
        self._last_activity = time.time()
        # 本人からの入力（追い連絡）の最終時刻。idle_seconds（手が空いているか）にだけ使い、
        # 固まりの判定（_last_activity = CLI の出力）には混ぜない。追い連絡で固まりの
        # 数えを戻していたせいで、本人が催促するほど立て直しが遅れていた（2026-10-29）。
        self._last_input = time.time()
        # CLI が道具を実行中（assistant の tool_use を出してから、その結果の user イベントが
        # 戻るまで）。この間の沈黙は長くても正常なので、固まりの上限を長い方にする。
        self._tool_in_flight = False

        # Current turn + a queue of pending follow-up texts.
        self._turn: Optional[_Turn] = None
        self._pending: "queue.Queue[str]" = queue.Queue()
        self._interrupt_sent = False
        # 追い連絡で割り込まれたターンの置き場所。ターン実行中に届いた最初の追い連絡の
        # サーバー受信時刻（DBの created_at）。割り込まれたターンの作業記録は、
        # この時刻の直前（= 追い連絡の上、元のメッセージの下）に置く。
        self._followup_anchor: Optional[str] = None
        # Receiver for CLI-INITIATED turns: the CLI fires a new model turn on its
        # own when a background task finishes while the session is idle (measured
        # and confirmed 2026-07-24 — same native wake as interactive Claude Code).
        # Without a sink those events were silently DROPPED, which is why Dan
        # stalled after "お待ちください". cli_runner installs a room-scoped sink
        # that classifies + persists these turns like any other.
        self.background_sink: Optional[EventSink] = None
        # True while a CLI-initiated (autonomous) turn is streaming.
        self._auto_active = False
        # _auto_active を見張る糸が動いている間 True（1本だけにする）。
        self._auto_watch_running = False
        # Set True when the last run_turn ended because the CLI went silent for
        # longer than the idle timeout (a real hang), as opposed to finishing.
        self._last_turn_hung = False
        # True while a run_turn loop is active. Guards against a second,
        # concurrent run_turn on the same session (e.g. a follow-up request that
        # raced is_turn_active and fell through to a fresh process_message_cli):
        # such a call must NOT start a parallel loop (that double-processes the
        # CLI output and double-saves) — it is routed as a follow-up instead.
        self._running = False
        # run_turn がこの回の最初の本文を CLI に書いた後 True（finally で戻す）。
        # それより前に届いた追い連絡は submit_room_followup が部屋の仮置きに入れ、
        # 本文を書いた直後に待ち行列へ移す（_send_user が目印を消した後に入れるため）。
        self._turn_sent = False

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
        return time.time() - max(self._last_activity, self._last_input)

    def silence_limit(self, timeout: float) -> float:
        """今の状態で、CLI がこれ以上黙ったら固まりとみなす秒数。"""
        if self._tool_in_flight:
            return timeout
        return min(timeout, _MODEL_SILENCE_TIMEOUT)

    def take_pending_followups(self) -> Optional[str]:
        """待ち行列に残った追い連絡を全部取り出す（固まって担当を捨てた後、新しい担当へ
        渡し直すため）。無ければ None。"""
        return self._drain_pending()

    # --- writing to the CLI --------------------------------------------
    def _write(self, obj: dict) -> None:
        proc = self._proc
        if not proc or not proc.stdin:
            raise RuntimeError("streaming session not started")
        proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    def _send_user(self, text: str) -> None:
        # 新しいターンが始まる = 待っていた追い連絡はここで送られる。前のターンの
        # 境界用の置き場所をこのターンへ持ち越さない。
        self._followup_anchor = None
        self._tool_in_flight = False
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
                # 戻り値は None にしない（2026-10-14）: None は「無音で終わった」の意味で、
                # 呼び出し側が「復元に失敗した」と見てセッションを止め直していた（動いている
                # 方のターンまで道連れになる）。
                self._pending.put(content)
                self._last_input = time.time()
                release_all_turn_claims(self.room_id)
                return {"type": "result", "subtype": "routed_as_followup", "is_error": False}
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
            self._take_discard_next(turn)
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
            # 最初の本文を書いた = 準備は終わり。準備中（起動待ち）に届いていた追い連絡を
            # ここで待ち行列へ移す（_send_user が目印を消した後なので、受信時刻の目印も
            # ここで立てる）。以後の追い連絡は submit_room_followup が直接待ち行列へ入れる。
            with _prep_lock:
                self._turn_sent = True
                _prep_claims.pop(self.room_id, None)
                waiting = _pre_queue.pop(self.room_id, [])
            for w_content, w_received in waiting:
                if w_received and self._followup_anchor is None:
                    self._followup_anchor = w_received
                self._pending.put(w_content)

            # Keep running follow-up turns until nothing is pending.
            last_result: Optional[TurnEvent] = None
            while True:
                if turn.done.wait(timeout=poll):
                    last_result = turn.result
                    from app.agent.provider_failover import exhausted
                    if last_result and exhausted(last_result):
                        break  # the other provider will take pending follow-ups
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
                if time.time() - self._last_activity > self.silence_limit(timeout):
                    hung = True
                    break
            return last_result
        finally:
            self._turn = None
            self._running = False
            self._turn_sent = False
            self._last_turn_hung = hung
            if hung:
                # Drop the poisoned/half-finished process; the next turn will
                # start a fresh CLI via start() in run_turn/get_or_create_session.
                self.stop()

    def submit_followup(self, content: str, received_at: Optional[str] = None) -> None:
        """Queue a follow-up. If a turn is in flight it will be applied at the
        next step boundary (interrupt → next turn); otherwise it is picked up
        as the next turn.

        received_at: この追い連絡のサーバー受信時刻（DB の created_at、ISO 文字列）。
        ターン実行中に届いた最初のものだけ覚え、割り込まれたターンの作業記録を
        その直前に置くために使う（take_followup_anchor）。"""
        if received_at and self._followup_anchor is None and self.is_turn_active():
            self._followup_anchor = received_at
        self._pending.put(content)
        self._last_input = time.time()

    def take_followup_anchor(self) -> Optional[str]:
        """割り込まれたターンの終わりに1回だけ読む。読んだら消える。"""
        anchor, self._followup_anchor = self._followup_anchor, None
        return anchor

    # --- prewarm (proactive rotation) ----------------------------------
    def prewarm(self, priming_text: str, sink: EventSink, timeout: float = 180.0) -> bool:
        """Start the process and prime it with context in the BACKGROUND so the
        next real user turn lands on a warm session (context already prefilled,
        KV cache built) instead of paying the fresh-session reseed cost on the
        critical path.

        Runs one priming turn whose output is discarded by the caller's sink
        (which also captures the session_id for --resume durability). Returns
        True if the session is alive and primed afterwards. Any failure returns
        False and the caller simply keeps the old session — the next send then
        takes the normal (slower) path, so prewarm is a pure optimization that
        can never break correctness."""
        try:
            if not self.is_alive():
                self.start()
            self.run_turn(priming_text, sink, timeout=timeout)
            return self.is_alive()
        except Exception:
            return False

    def discard_next_turn(self, ttl: float = 5.0) -> None:
        """The message the next turn will answer was withdrawn: whatever that turn produces is not kept."""
        self._discard_next_until = time.time() + ttl

    def _take_discard_next(self, turn) -> None:
        until = getattr(self, "_discard_next_until", 0.0)
        if until and time.time() < until:
            self._discard_next_until = 0.0
            self._discard_turn = turn

    def clear_pending(self) -> None:
        """Drop follow-ups not yet given to the CLI (the user withdrew them by cancelling)."""
        while True:
            try:
                self._pending.get_nowait()
            except queue.Empty:
                return

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
                    # stderr はここに混ざる（stderr=STDOUT）。担当が JSON 以外で出した言葉は、
                    # 固まる直前の手がかりになるので捨てずに部屋の記録へ残す。固まりの数え
                    # （_last_activity）はモデルの返事（JSON）だけで進める。
                    self._record_stray(line)
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

    def _record_stray(self, line: str) -> None:
        try:
            _cli_record.stray_line(self.room_id, "claude", line)
        except Exception:
            pass

    def _dispatch(self, ev: TurnEvent) -> None:
        typ = ev.get("type")
        turn = self._turn
        self._note_tool_state(typ, ev)

        # --- CLI-initiated (autonomous) turn: no run_turn loop is waiting. ---
        # The CLI woke itself (a background task finished while idle). Route the
        # whole turn to the room's background sink so it is classified, saved
        # and rendered like any other turn instead of being dropped.
        if turn is None:
            if ev.get("parent_tool_use_id"):
                # 裏の担当（Agent）の出力。担当本体のターンではないので「仕事中」の印に
                # しない。2026-10-30 X顧問の部屋: 返事の直後に起こした裏の手伝いの言葉で
                # _auto_active が立ち、本体の result は来ないので解けず、その後の本人の
                # 言葉が全部待ち行列に溜まったまま届かなかった。
                return
            if typ == "assistant" and not self._auto_active:
                self._begin_auto_turn()
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
                self._end_auto_turn()
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


    # --- CLI-initiated (autonomous) turn bookkeeping ---------------------
    def _begin_auto_turn(self) -> None:
        self._auto_active = True
        if not self._auto_watch_running:
            self._auto_watch_running = True
            threading.Thread(target=self._auto_watch, daemon=True).start()

    def _end_auto_turn(self) -> None:
        """担当が自分で始めたターンの終わり。待たせていた本人の言葉があれば、それを次の
        ターンとして送る（出力は同じ background sink が保存・表示する）。"""
        self._auto_active = False
        self._interrupt_sent = False
        follow = self._drain_pending()
        if follow is not None:
            try:
                self._send_user(follow)
                self._begin_auto_turn()
            except Exception:
                pass

    def _auto_watch(self) -> None:
        """自分で始めたターンの沈黙を見張る。result が来ないまま黙り続けたら終わったと
        みなす（割り込み後は短く、それ以外は固まりの上限で）。run_turn の輪が無い間の
        唯一の見張り。"""
        try:
            while self.is_alive() and self._auto_active:
                silent = time.time() - self._last_activity
                if self._interrupt_sent and not self._pending.empty():
                    limit = _AUTO_INTERRUPT_GRACE
                else:
                    limit = self.silence_limit(_AUTO_TURN_SILENCE_TIMEOUT)
                if silent > limit:
                    self._record_stray(
                        f"[auto-turn] no result for {int(silent)}s (interrupt_sent={self._interrupt_sent}, "
                        f"pending={self._pending.qsize()}); treating the CLI-initiated turn as over"
                    )
                    self._end_auto_turn()
                    continue
                time.sleep(_AUTO_WATCH_POLL)
        finally:
            self._auto_watch_running = False
            if self._auto_active and self.is_alive():
                # _end_auto_turn が次のターンを送って _auto_active を立て直した直後に
                # 糸が終わる場合: 見張りを張り直す
                self._begin_auto_turn()

    def _note_tool_state(self, typ: Optional[str], ev: TurnEvent) -> None:
        """assistant が tool_use を出したら道具の実行中、その結果（user）か result が来たら
        終わり。固まりの上限をどちらで見るかに使う。"""
        if typ == "assistant":
            content = (ev.get("message") or {}).get("content")
            self._tool_in_flight = bool(
                isinstance(content, list)
                and any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
            )
        elif typ in ("user", "result"):
            self._tool_in_flight = False


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


# --- 起動待ちの間に届いた追い連絡（2026-10-14） -----------------------------
# 1通目の送信から run_turn が最初の本文を CLI に書くまでには、文脈の組み立て（DB）・
# プロセスの起動・再注入があり、数秒かかる（DB が遅いと 4〜5 秒）。その間は
# is_turn_active() が False なので、追い連絡は「方針変更」扱いで前のターンを止めて
# いた（画面に streaming session not started が出て、作業の記録が全部追い連絡の下に
# 付く。2026-10-13 実測）。ここでは「準備中」も実行中と同じに扱い、その間の発言は
# 追い連絡として待たせる。待たせた分は run_turn が最初の本文を書いた直後に待ち行列へ
# 移し、いつもの区切りの割り込みで反映する。
_prep_lock = threading.Lock()
_prep_claims: Dict[str, Dict[object, float]] = {}   # room -> {token: いつ取ったか}
_pre_queue: Dict[str, list] = {}                     # room -> [(本文, 受信時刻)]
_CLAIM_TTL = 120.0   # 準備が例外などで終わらなかった時の保険。これより古い印は無視する


def claim_turn(room_id: str) -> object:
    """ターンの準備を始めた印を立てる。run_turn が本文を書いた時点で外れる
    （release_all_turn_claims）。呼び出し側は念のため finally で release_turn_claim する。"""
    token = object()
    with _prep_lock:
        _prep_claims.setdefault(room_id, {})[token] = time.time()
    return token


def release_turn_claim(room_id: str, token: object) -> None:
    with _prep_lock:
        claims = _prep_claims.get(room_id)
        if claims:
            claims.pop(token, None)
            if not claims:
                _prep_claims.pop(room_id, None)


def release_all_turn_claims(room_id: str) -> None:
    with _prep_lock:
        _prep_claims.pop(room_id, None)


def _has_live_claim(room_id: str) -> bool:
    """_prep_lock を持って呼ぶ。古い印は捨てる。"""
    claims = _prep_claims.get(room_id)
    if not claims:
        return False
    now = time.time()
    for token, at in list(claims.items()):
        if now - at > _CLAIM_TTL:
            claims.pop(token, None)
    if not claims:
        _prep_claims.pop(room_id, None)
        return False
    return True


def is_turn_active_or_preparing(room_id: str) -> bool:
    """ターンが実行中、または準備中（claim_turn 済みで run_turn がまだ本文を書いていない）。
    chat_routes はこれが True の時、新しい発言を追い連絡として待たせる。"""
    s = get_session(room_id)
    if s is not None and s.is_turn_active():
        return True
    with _prep_lock:
        return _has_live_claim(room_id)


def submit_room_followup(room_id: str, content: str, received_at: Optional[str] = None) -> str:
    """追い連絡を部屋へ渡す。ターンが本文を書いた後なら、そのセッションの待ち行列へ
    （submit_followup）。まだ準備中なら部屋の仮置きへ入れ、run_turn が最初の本文を書いた
    直後に待ち行列へ移す（目印の受信時刻も一緒に運ぶ）。戻り値はどちらに入れたか。"""
    with _prep_lock:
        s = get_session(room_id)
        if s is not None and s.is_turn_active() and (s._turn_sent or s._auto_active):
            s.submit_followup(content, received_at)
            return "session"
        _pre_queue.setdefault(room_id, []).append((content, received_at))
        return "pre_queue"


def pending_pre_queue(room_id: str) -> int:
    with _prep_lock:
        return len(_pre_queue.get(room_id) or [])


def get_or_create_session(
    room_id: str,
    build_cmd: Callable[[], list],
    env: Dict[str, str],
    cwd: str,
    *,
    model: Optional[str] = None,
) -> StreamingSession:
    with _registry_lock:
        s = _sessions.get(room_id)
        if s and s.is_alive():
            if model is None or s.model == model:
                return s
            if s.is_turn_active():
                raise RuntimeError("Cannot switch model during an active turn")
            s.stop()
        s = StreamingSession(room_id, build_cmd, env, cwd)
        s.model = model
        _sessions[room_id] = s
    s.start()
    return s


def has_active_session(room_id: str) -> bool:
    s = get_session(room_id)
    return bool(s and s.is_alive())


def install_session(room_id: str, session: "StreamingSession") -> Optional["StreamingSession"]:
    """Atomically make `session` the room's session, returning the one it
    replaced (the caller stops it). Used by proactive rotation to swap in a
    prewarmed replacement without a window where the room has no session."""
    with _registry_lock:
        old = _sessions.get(room_id)
        _sessions[room_id] = session
    return old


def swap_idle_session(
    room_id: str, session: "StreamingSession", expected: Optional["StreamingSession"],
) -> Tuple[bool, Optional["StreamingSession"]]:
    """install_session, but only while the room still holds `expected` (or no
    live session) with no turn running on it. Returns (swapped, replaced).

    The room's session can change while a replacement is being primed: a new
    turn may recycle it and start on a fresh one. Swapping then stops the
    session that turn is running on, and the turn ends with nothing done
    (2026-09-25: a monthly watch's turn was lost this way)."""
    with _registry_lock:
        current = _sessions.get(room_id)
        if current is not None and current.is_alive() and (
            current is not expected or current.is_turn_active()
        ):
            return False, None
        _sessions[room_id] = session
    return True, current
