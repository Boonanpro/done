import json

import pytest

from app.agent import model_catalog as mc


@pytest.fixture
def codex_list(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "_CODEX_HOME", tmp_path)
    monkeypatch.setattr(mc, "_codex_cached", (-1.0, []))
    monkeypatch.setattr(mc, "_CLAUDE_STORE", tmp_path / "claude.json")
    monkeypatch.setattr(mc, "_claude_state", {"loaded": True, "data": None, "next_try": float("inf"), "running": False})

    def write(models):
        path = tmp_path / "models_cache.json"
        path.write_text(json.dumps({"models": models}), encoding="utf-8")
        mc._codex_cached = (-1.0, [])
    return write


TODAY = [
    {"slug": "gpt-6.1-sol", "display_name": "GPT-6.1-Sol", "visibility": "list", "priority": 1},
    {"slug": "gpt-6-astra", "display_name": "GPT-6-Astra", "visibility": "list", "priority": 2},
    {"slug": "gpt-6.1-terra", "display_name": "GPT-6.1 Terra", "visibility": "list", "priority": 3},
    {"slug": "gpt-6-sol", "display_name": "GPT-6-Sol", "visibility": "list", "priority": 4},
    {"slug": "gpt-reserve", "display_name": "GPT-Reserve", "visibility": "hide", "priority": 4},
    {"slug": "gpt-6-luna", "display_name": "GPT-6-Luna", "visibility": "list", "priority": 5},
    {"slug": "gpt-5.6-sol", "display_name": "GPT-5.6-Sol", "visibility": "list", "priority": 6},
    {"slug": "codex-auto-review", "display_name": "Codex Auto Review", "visibility": "hide", "priority": 43},
]


def test_picker_offers_newest_version_of_each_gpt_tier(codex_list):
    codex_list(TODAY)
    assert [(o["id"], o["label"]) for o in mc.codex_options()] == [
        ("gpt-6.1-sol", "GPT-6.1 Sol"), ("gpt-6-astra", "GPT-6 Astra"),
        ("gpt-6.1-terra", "GPT-6.1 Terra"), ("gpt-6-luna", "GPT-6 Luna"),
    ]


def test_new_release_reaches_picker_and_saved_rooms(codex_list):
    codex_list(TODAY)
    assert mc.current("gpt-6-astra") == "gpt-6-astra"
    assert not mc.is_allowed("gpt-6.1-astra")
    codex_list(TODAY + [{"slug": "gpt-6.1-astra", "display_name": "GPT-6.1-Astra", "visibility": "list", "priority": 0}])
    assert mc.codex_options()[0] == {"id": "gpt-6.1-astra", "label": "GPT-6.1 Astra", "backend": "codex"}
    assert "gpt-6-astra" not in [o["id"] for o in mc.codex_options()]
    assert mc.current("gpt-6-astra") == "gpt-6.1-astra"      # rooms and jobs saved on 6 Astra move up
    assert mc.current("gpt-5.6-sol") == "gpt-6.1-sol"
    assert mc.is_allowed("gpt-6.1-astra") and mc.is_allowed("gpt-6-astra")


def test_hidden_models_are_not_offered_or_upgraded_to(codex_list):
    codex_list(TODAY + [{"slug": "gpt-7-astra", "display_name": "GPT-7-Astra", "visibility": "hide", "priority": 0}])
    assert mc.current("gpt-6-astra") == "gpt-6-astra"
    assert "gpt-7-astra" not in [o["id"] for o in mc.codex_options()]


def test_codex_list_missing_falls_back(codex_list):
    assert [o["id"] for o in mc.codex_options()][0] == "gpt-6-astra"
    assert mc.is_codex_model("gpt-6-astra") and not mc.is_codex_model("opus")


def test_claude_labels_follow_newest_and_new_family_is_offered(codex_list):
    families = mc.newest_claude_families([
        {"id": "claude-opus-5-5", "display_name": "Claude Opus 5.5", "created_at": "2026-09-21"},
        {"id": "claude-opus-6", "display_name": "Claude Opus 6", "created_at": "2026-12-01"},
        {"id": "claude-sonnet-5-5", "display_name": "Claude Sonnet 5.5"},
        {"id": "claude-sonnet-4-5-20250929", "display_name": "Claude Sonnet 4.5"},
        {"id": "claude-nova-1", "display_name": "Claude Nova 1"},
    ])
    mc._claude_state["data"] = {"checked_at": 0, "families": families}
    options = mc.claude_options()
    assert {"id": "opus", "label": "Claude Opus 6", "backend": "claude"} in options
    assert {"id": "sonnet", "label": "Claude Sonnet 5.5", "backend": "claude"} in options
    assert {"id": "fable", "label": "Claude Fable 5.1", "backend": "claude"} in options   # not listed yet: kept
    assert {"id": "claude-nova-1", "label": "Claude Nova 1", "backend": "claude"} in options
    assert mc.is_allowed("claude-nova-1") and mc.current("opus") == "opus"


def test_old_list_is_read_again_in_background(codex_list, monkeypatch):
    calls = []
    monkeypatch.setattr(mc, "_refresh_claude", lambda: calls.append(1))
    mc._claude_state["next_try"] = 0.0
    mc._claude_families(wait=True)
    assert calls == [1]
