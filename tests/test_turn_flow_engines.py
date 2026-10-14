"""A message that arrives while Dan works: the same rules on every engine (2026-10-14).

The rules are in docs/current/chat-timeline-definition.md and live in app/agent/turn_flow.py. Every test here runs on each
engine listed in turn_flow.ENGINES, so a rule cannot hold on one engine only, and an engine added later is covered as soon
as it is listed.

Before: the rules were written inside the Claude path. In a room on GPT the record of the turn a follow-up stopped was placed
when it was saved, 0.7 s after the follow-up (the owner saw two messages in a row, 09:34), and a follow-up sent within two
minutes of the first message was parked where nothing read it (Dan never answered it)."""
import ast
import queue
import threading
from pathlib import Path

import pytest

from app.agent import cli_runner as cr
from app.agent import codex_runner
from app.agent import streaming_session as ss
from app.agent import turn_flow

ROOT = Path(__file__).resolve().parents[1]
ENGINES = sorted(turn_flow.ENGINES)
ROOM, RUN = "room-turn-flow", "run-turn-flow"
FOLLOW_UP = "2026-10-14T00:34:15.21329+00:00"            # as the database returns it (trailing zero dropped)
JUST_BEFORE = "2026-10-14T00:34:15.212290+00:00"


@pytest.fixture(autouse=True)
def clean():
    def wipe():
        with ss._prep_lock:
            ss._prep_claims.pop(ROOM, None)
            ss._pre_queue.pop(ROOM, None)
        with ss._registry_lock:
            ss._sessions.pop(ROOM, None)
        with turn_flow._lock:
            turn_flow._stopped.clear()
    wipe()
    yield
    wipe()


def resident(monkeypatch, on=True):
    monkeypatch.setenv("DAN_STREAMING_INPUT", "1" if on else "0")


def test_every_model_on_offer_runs_on_a_listed_engine():
    for option in cr.CLI_MODEL_OPTIONS:
        assert turn_flow.engine_of(option["id"]) == option["backend"]
        assert option["backend"] in turn_flow.ENGINES
    assert turn_flow.engine_of(None) in turn_flow.ENGINES          # no model saved for the room: the default
    assert turn_flow.engine_of("not-a-model") in turn_flow.ENGINES


# --- the message is read by Dan ------------------------------------------------------------------------------------

# What each engine's own turn code does with a message handed to it while it runs, written out here on purpose and not
# taken from turn_flow: the resident Claude session takes waiting messages at its next step (streaming_session.run_turn);
# a GPT turn is one `codex exec` with its input closed, so nothing would ever take a waiting message out again.
TAKES_A_WAITING_MESSAGE = {"claude": True, "codex": False}


def test_every_engine_is_stated_here_too():
    assert set(TAKES_A_WAITING_MESSAGE) == set(turn_flow.ENGINES)
    assert {e: v["reads_mid_turn"] for e, v in turn_flow.ENGINES.items()} == TAKES_A_WAITING_MESSAGE


def working(state):
    """Put the room in one of the states a message can find it in."""
    if state == "preparing":
        ss.claim_turn(ROOM)
    elif state == "running":
        session = ss.StreamingSession(ROOM, lambda: ["x"], {}, "D:/")
        session.is_alive = lambda: True
        session._turn = object()
        session._turn_sent = True
        with ss._registry_lock:
            ss._sessions[ROOM] = session


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("state", ["idle", "preparing", "running"])
@pytest.mark.parametrize("flag", [True, False])
def test_a_message_waits_only_where_the_running_turn_will_read_it(engine, state, flag, monkeypatch):
    resident(monkeypatch, flag)
    working(state)
    waits = turn_flow.waits_for_running_turn(ROOM, engine)
    assert waits == (TAKES_A_WAITING_MESSAGE[engine] and flag and state != "idle")
    if waits:                                   # handed over: it sits where the turn takes it from
        assert ss.submit_room_followup(ROOM, "follow-up", FOLLOW_UP) in ("session", "pre_queue")
    else:                                       # a new turn starts with it; nothing is parked
        assert ss.pending_pre_queue(ROOM) == 0


@pytest.mark.parametrize("engine", ENGINES)
def test_a_new_turn_makes_later_messages_wait_only_on_an_engine_that_reads_mid_turn(engine, monkeypatch):
    resident(monkeypatch)
    token = turn_flow.claim_new_turn(ROOM, engine)
    assert (token is not None) == TAKES_A_WAITING_MESSAGE[engine]
    assert turn_flow.waits_for_running_turn(ROOM, engine) == TAKES_A_WAITING_MESSAGE[engine]
    assert ss.is_turn_active_or_preparing(ROOM) == TAKES_A_WAITING_MESSAGE[engine]     # no mark is left in a room that cannot use it
    turn_flow.release_claim(ROOM, token)
    assert turn_flow.waits_for_running_turn(ROOM, engine) is False


# --- the record of the work so far goes just before the message -------------------------------------------------------

RESULT = {
    "session_id": None, "is_error": False, "result_text": "始めます", "final_text_parts": ["始めます"], "errors": [],
    "reasoning_steps": ["🔧 コマンド実行"], "reasoning_full": [], "written_file_paths": [],
    "turn_blocks": [{"type": "text", "text": "始めます"}, {"type": "tool", "name": "Bash", "label": "コマンド実行"}],
}


def quiet(monkeypatch, saved):
    """The parts around a turn's end that reach outside the process."""
    monkeypatch.setattr(cr, "_save_ai_message_sync", lambda room, text, *a, **k: saved.append(k) or "message-id")
    monkeypatch.setattr(cr, "_save_execution_event_sync", lambda *a, **k: None)
    monkeypatch.setattr(cr, "_update_run_sync", lambda *a, **k: None)
    monkeypatch.setattr(cr, "_save_session", lambda *a, **k: None)
    monkeypatch.setattr(cr, "_cleanup_mcp_config", lambda *a, **k: None)
    monkeypatch.setattr(cr, "_start_run_heartbeat", lambda run: threading.Event())


def end_a_turn_on_codex(monkeypatch, result):
    saved = []
    quiet(monkeypatch, saved)
    monkeypatch.setattr(codex_runner, "resolve_codex_cli", lambda: "codex")
    monkeypatch.setattr(codex_runner, "_codex_env", lambda room, project: {})
    monkeypatch.setattr(codex_runner, "build_codex_profile", lambda *a, **k: "profile")
    monkeypatch.setattr(codex_runner, "build_codex_cmd", lambda *a, **k: ["codex"])
    monkeypatch.setattr(codex_runner, "cleanup_codex_profile", lambda room: None)
    monkeypatch.setattr(codex_runner, "run_codex_process", lambda *a, **k: result() if callable(result) else result)
    codex_runner.run_codex_turn_in_thread("message", "system", "mcp.json", ROOM, queue.Queue(), project_id="project", run_id=RUN)
    return saved


def end_a_turn_on_claude(monkeypatch, result):
    """The one-process-per-turn path (the resident path's end is covered by the source check below)."""
    import app.services.compaction_sync as compaction_sync
    saved = []
    quiet(monkeypatch, saved)
    monkeypatch.setattr(compaction_sync, "sync_compaction_summaries", lambda: 0)
    monkeypatch.setattr(cr, "_resolve_claude_cli", lambda: ("claude", None))
    monkeypatch.setattr(cr, "_resolve_cli_model", lambda room=None: "opus")
    monkeypatch.setattr(cr, "_dan_compact_launch", lambda user: ([], {}))
    monkeypatch.setattr(cr, "_build_cli_cmd", lambda *a, **k: ["claude"])
    monkeypatch.setattr(cr, "_run_cli_process", lambda *a, **k: result() if callable(result) else result)
    cr._run_cli_in_thread("message", "system", "mcp.json", ROOM, queue.Queue(), project_id="project", run_id=RUN)
    return saved


END_A_TURN = {"claude": end_a_turn_on_claude, "codex": end_a_turn_on_codex}


def test_every_engine_has_its_turn_end_under_test():
    assert set(END_A_TURN) == set(turn_flow.ENGINES)


@pytest.mark.parametrize("engine", ENGINES)
def test_the_record_of_a_turn_a_message_stopped_goes_just_before_that_message(engine, monkeypatch):
    turn_flow.stopped_by_message(RUN, FOLLOW_UP)
    saved = END_A_TURN[engine](monkeypatch, RESULT)
    assert [s["created_at"] for s in saved] == [JUST_BEFORE]
    assert saved[0]["blocks"] == RESULT["turn_blocks"]            # the work log is kept whole


@pytest.mark.parametrize("engine", ENGINES)
def test_a_turn_nothing_cut_into_is_placed_when_it_is_saved(engine, monkeypatch):
    turn_flow.stopped_by_message("another-run", FOLLOW_UP)
    saved = END_A_TURN[engine](monkeypatch, RESULT)
    assert [s["created_at"] for s in saved] == [None]             # None = the database's clock at the save


@pytest.mark.parametrize("engine", ENGINES)
def test_a_stopped_turn_that_ends_in_an_error_is_placed_before_the_message_too(engine, monkeypatch):
    def broken():
        raise RuntimeError("the process was stopped")
    turn_flow.stopped_by_message(RUN, FOLLOW_UP)
    saved = END_A_TURN[engine](monkeypatch, broken)
    assert [s["created_at"] for s in saved] == [JUST_BEFORE]


def test_the_note_of_a_stop_is_used_once_and_only_by_that_run():
    turn_flow.stopped_by_message(RUN, FOLLOW_UP)
    turn_flow.stopped_by_message(RUN, "2026-10-14T00:40:00+00:00")       # a second message: the first one cut in
    assert turn_flow.record_time("another-run") is None
    assert turn_flow.record_time(RUN) == JUST_BEFORE
    assert turn_flow.record_time(RUN) is None                             # the next turn of the run is not moved
    assert turn_flow.record_time(None) is None
    assert turn_flow.record_time(RUN, handed_over_at=FOLLOW_UP) == JUST_BEFORE   # read mid-turn: the turn knows the time itself


def test_a_stop_noted_before_the_message_has_a_saved_time_uses_now():
    turn_flow.stopped_by_message(RUN, None)
    assert turn_flow.record_time(RUN) is not None


# --- nothing in the engines' code goes around the one place --------------------------------------------------------

def calls(path, name):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", None)) == name]


def test_every_save_of_a_turns_record_states_its_time():
    """A save without created_at is placed by the database's clock, which is how the record fell below the follow-up."""
    for path in sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "app" / "agent").glob("*.py")):
        for call in calls(path, "_save_ai_message_sync"):
            assert "created_at" in [k.arg for k in call.keywords], f"{path}:{call.lineno}"


def test_each_engines_turn_end_asks_the_one_place_for_the_time():
    asked = {}
    for path in ("app/agent/cli_runner.py", "app/agent/codex_runner.py"):
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            asked[fn.name] = any(
                isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "record_time" for n in ast.walk(fn))
    for turn_end in ("_run_cli_in_thread", "_process_via_streaming_session", "run_codex_turn_in_thread"):
        assert asked[turn_end], turn_end


def test_the_send_entrance_decides_through_the_one_place():
    source = (ROOT / "app/api/chat_routes.py").read_text(encoding="utf-8")
    assert "turn_flow.waits_for_running_turn(" in source and "turn_flow.stopped_by_message(" in source
    assert "is_turn_active_or_preparing" not in source      # asked without the engine, a GPT room waited on nothing
    assert "claim_turn" not in source.replace("turn_flow.claim_new_turn", "")
