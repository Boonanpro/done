from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent import cli_runner as cr, streaming_session as ss
from app.api import chat_routes as routes


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(cr, "_room_model_cache", {})
    monkeypatch.setattr(ss, "_sessions", {})


@pytest.mark.parametrize("option", cr.CLI_MODEL_OPTIONS)
def test_explicit_model_survives_exhausted_fable_guard(monkeypatch, option):
    from app.agent import usage_guard
    from app.services import supabase_client
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"metadata": {"model": option["id"]}}
    ]
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: SimpleNamespace(client=db))
    monkeypatch.setattr(usage_guard, "fable_quota_exhausted", lambda: True)
    assert cr.resolve_room_backend("room") == (option["id"], option["backend"])


def test_unselected_default_keeps_existing_quota_policy(monkeypatch):
    from app.agent import usage_guard
    monkeypatch.setenv("DAN_CLI_MODEL", "fable")
    monkeypatch.setattr(usage_guard, "fable_quota_exhausted", lambda: True)
    assert cr.resolve_room_backend(None) == ("opus", "claude")


@pytest.mark.parametrize("option", cr.CLI_MODEL_OPTIONS)
@pytest.mark.asyncio
async def test_switch_api_persists_and_reports_all_options(monkeypatch, option):
    from app.services import project_service, supabase_client
    project = {"id": "project", "metadata": {"model": "opus", "keep": True}}
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.side_effect = (
        lambda: SimpleNamespace(data=[{"metadata": project["metadata"]}])
    )
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: SimpleNamespace(client=db))
    monkeypatch.setattr(project_service, "ProjectService", lambda: SimpleNamespace(supabase=db))
    monkeypatch.setattr(routes, "_project_for_session", AsyncMock(return_value=project))
    monkeypatch.setattr(cr, "is_cli_active", lambda _: False)
    process = MagicMock(model="opus")
    process.is_turn_active.return_value = False
    monkeypatch.setattr(ss, "get_session", lambda _: process)
    result = await routes.set_dan_session_model("room", routes.SessionModelRequest(model=option["id"]), SimpleNamespace(user_id="user"))
    assert result["selected_model"] == result["effective_model"] == option["id"]
    assert result["backend"] == option["backend"]
    db.table.return_value.update.assert_called_once_with({"metadata": {"model": option["id"], "keep": True}})
    assert process.stop.call_count == int(option["id"] != "opus")


@pytest.mark.asyncio
async def test_active_turn_rejects_switch_without_saving(monkeypatch):
    monkeypatch.setattr(routes, "_project_for_session", AsyncMock(return_value={"id": "p"}))
    monkeypatch.setattr(cr, "is_cli_active", lambda _: True)
    monkeypatch.setattr(ss, "get_session", lambda _: None)
    with pytest.raises(routes.HTTPException) as error:
        await routes.set_dan_session_model("room", routes.SessionModelRequest(model="fable"), SimpleNamespace(user_id="user"))
    assert error.value.status_code == 409


def test_persistent_process_replaced_on_same_backend_switch(monkeypatch):
    old = MagicMock(model="opus")
    old.is_turn_active.return_value = False
    ss._sessions["room"] = old
    monkeypatch.setattr(ss.StreamingSession, "start", lambda _: None)
    new = ss.get_or_create_session("room", lambda: ["claude", "--model", "fable"], {}, ".", model="fable")
    old.stop.assert_called_once()
    assert new.model == "fable"
    assert new._build_cmd()[-1] == "fable"


def test_persistent_process_reused_for_same_model():
    old = MagicMock(model="fable")
    ss._sessions["room"] = old
    assert ss.get_or_create_session("room", lambda: [], {}, ".", model="fable") is old
    old.stop.assert_not_called()


def test_persistent_active_turn_not_killed_for_switch():
    old = MagicMock(model="opus")
    ss._sessions["room"] = old
    with pytest.raises(RuntimeError, match="active turn"):
        ss.get_or_create_session("room", lambda: [], {}, ".", model="fable")
    old.stop.assert_not_called()
