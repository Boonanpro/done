"""Jev 短縮プラグイン（services/claude-plugins/dan-compact）を Claude Code 起動に付ける配線のテスト。

- DAN_COMPACT_JEV=0 / 鍵なし / プラグインのファイルなし → 何も付けない（今までどおり）
- 鍵あり → --plugin-dir とフック有効化の env だけ足す。他の引数は不変
- 鍵はデバッグログに出ない
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent import cli_runner as cr
from app.services import work_locks as _work_locks

KEY = "tsk_UNIT_TEST_KEY_123456"


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(cr, "_typesafe_key_cache", {})
    monkeypatch.delenv("DAN_COMPACT_JEV", raising=False)
    for name in cr._DAN_COMPACT_ENV_PASSTHROUGH:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cr, "_dotenv_value", lambda name: "")
    # 本物のプラグインの置き場所の代わりに、マニフェストとライブラリだけ置いた一時フォルダ
    plugin = tmp_path / "dan-compact"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text('{"name":"dan-compact"}', encoding="utf-8")
    lib = plugin / "node_modules" / "fast-jev-compaction" / "dist"
    lib.mkdir(parents=True)
    (lib / "compact.js").write_text("export {}", encoding="utf-8")
    monkeypatch.setattr(cr, "_DAN_COMPACT_PLUGIN_DIR", plugin)
    logs: list[str] = []
    monkeypatch.setattr(cr, "_cli_debug", logs.append)
    yield SimpleNamespace(plugin=plugin, logs=logs)


def _fake_credentials(monkeypatch, found: dict):
    class Service:
        calls: list = []

        async def get_credential(self, user_id, service):
            Service.calls.append((user_id, service))
            return found.get(service)

    from app.services import credentials_service
    monkeypatch.setattr(credentials_service, "get_credentials_service", lambda: Service())
    return Service


def test_disabled_by_flag_adds_nothing(monkeypatch, isolate):
    monkeypatch.setenv("DAN_COMPACT_JEV", "0")
    monkeypatch.setattr(cr, "_typesafe_api_key_sync", lambda uid: KEY)
    assert cr._dan_compact_launch("user") == ([], {})
    assert any("DAN_COMPACT_JEV=0" in line for line in isolate.logs)


def test_flag_from_dotenv_disables(monkeypatch):
    monkeypatch.setattr(cr, "_dotenv_value", lambda name: "0" if name == "DAN_COMPACT_JEV" else "")
    assert cr._dan_compact_enabled() is False
    monkeypatch.setenv("DAN_COMPACT_JEV", "1")
    assert cr._dan_compact_enabled() is True, "プロセス環境が .env より優先"


def test_default_is_enabled():
    assert cr._dan_compact_enabled() is True


def test_no_key_adds_nothing(monkeypatch, isolate):
    monkeypatch.setattr(cr, "_typesafe_api_key_sync", lambda uid: None)
    assert cr._dan_compact_launch("user") == ([], {})
    assert any("no TypeSafe key" in line for line in isolate.logs)


def test_missing_plugin_files_adds_nothing(monkeypatch, isolate):
    monkeypatch.setattr(cr, "_typesafe_api_key_sync", lambda uid: KEY)
    monkeypatch.setattr(cr, "_DAN_COMPACT_PLUGIN_DIR", isolate.plugin / "nowhere")
    assert cr._dan_compact_launch("user") == ([], {})


def test_key_present_adds_plugin_dir_and_env_only(monkeypatch, isolate):
    monkeypatch.setattr(cr, "_typesafe_api_key_sync", lambda uid: KEY)
    args, env = cr._dan_compact_launch("user")
    assert args == ["--plugin-dir", str(isolate.plugin)]
    assert env["CLAUDE_CODE_ENABLE_FUNCTION_HOOKS"] == "1"
    assert env["TYPESAFE_API_KEY"] == KEY
    assert env["DAN_COMPACT_LEDGER_PATH"].endswith(".compact_jev_ledger.json")
    assert set(env) == {"CLAUDE_CODE_ENABLE_FUNCTION_HOOKS", "TYPESAFE_API_KEY", "DAN_COMPACT_LEDGER_PATH"}
    assert KEY not in "\n".join(isolate.logs), "鍵はデバッグログに出ない"
    assert any("jev plugin attached" in line for line in isolate.logs)


def test_dotenv_compact_settings_pass_through(monkeypatch, isolate):
    monkeypatch.setattr(cr, "_typesafe_api_key_sync", lambda uid: KEY)
    values = {"DAN_COMPACT_KEEP_THRESHOLD": "0.4", "DAN_COMPACT_MONTHLY_CAP_JPY": "50", "DAN_COMPACT_LEDGER_PATH": "X:/ledger.json"}
    monkeypatch.setattr(cr, "_dotenv_value", lambda name: values.get(name, ""))
    _, env = cr._dan_compact_launch("user")
    assert env["DAN_COMPACT_KEEP_THRESHOLD"] == "0.4"
    assert env["DAN_COMPACT_MONTHLY_CAP_JPY"] == "50"
    assert env["DAN_COMPACT_LEDGER_PATH"] == "X:/ledger.json"
    # プロセス環境に既にあるものは（子に自動で届くので）足さない
    monkeypatch.setenv("DAN_COMPACT_KEEP_THRESHOLD", "0.2")
    _, env2 = cr._dan_compact_launch("user")
    assert "DAN_COMPACT_KEEP_THRESHOLD" not in env2


def test_build_cli_cmd_unchanged_without_extra_args_and_appends_with():
    base = cr._build_cli_cmd("claude", None, "mcp.json", "SYS", "sid", fork_session=True, model="fable")
    assert base == [
        "claude", "-p", "--output-format", "stream-json", "--include-partial-messages", "--verbose",
        "--dangerously-skip-permissions", "--model", "fable", "--mcp-config", "mcp.json",
        "--append-system-prompt", "SYS", "--disallowedTools", "ExitPlanMode,AskUserQuestion",
        "--settings", _work_locks.hook_settings(),   # main の並行作業（ファイルの順番待ちフック）
        "--resume", "sid", "--fork-session",
    ]
    with_plugin = cr._build_cli_cmd("claude", None, "mcp.json", "SYS", "sid", fork_session=True, model="fable",
                                    extra_args=["--plugin-dir", "P"])
    assert with_plugin == base + ["--plugin-dir", "P"]
    assert cr._build_cli_cmd("node", "cli.js", "m", "S", None, extra_args=[]) == cr._build_cli_cmd("node", "cli.js", "m", "S", None)


def test_key_lookup_uses_credential_service_names_and_caches(monkeypatch):
    service = _fake_credentials(monkeypatch, {
        "typesafe_jev": {"credential_type": "api_key", "password": KEY},
    })
    assert cr._typesafe_api_key_sync("user-1") == KEY
    assert service.calls == [("user-1", "typesafe"), ("user-1", "typesafe_jev")]
    assert cr._typesafe_api_key_sync("user-1") == KEY
    assert len(service.calls) == 2, "2回目はキャッシュ"
    assert cr._typesafe_api_key_sync(None) is None


def test_key_lookup_rejects_non_api_key_and_handles_errors(monkeypatch, isolate):
    _fake_credentials(monkeypatch, {"typesafe": {"credential_type": "login", "password": "pw"}})
    assert cr._typesafe_api_key_sync("user-2") is None

    class Broken:
        async def get_credential(self, user_id, service):
            raise RuntimeError("db down " + KEY)

    from app.services import credentials_service
    monkeypatch.setattr(credentials_service, "get_credentials_service", lambda: Broken())
    assert cr._typesafe_api_key_sync("user-3") is None
    assert KEY not in "\n".join(isolate.logs)


@pytest.mark.asyncio
async def test_key_lookup_works_from_a_running_event_loop(monkeypatch):
    _fake_credentials(monkeypatch, {"typesafe": {"credential_type": "api_key", "password": KEY}})
    import asyncio
    assert await asyncio.to_thread(cr._typesafe_api_key_sync, "user-4") == KEY
    # ループが動いているスレッドから直接呼んでも、別スレッドで asyncio.run するので落ちない
    assert cr._typesafe_api_key_sync("user-5") == KEY


def test_real_plugin_folder_is_complete():
    plugin = Path(cr.__file__).resolve().parents[2] / "services" / "claude-plugins" / "dan-compact"
    assert (plugin / ".claude-plugin" / "plugin.json").exists()
    assert (plugin / "hooks" / "hooks.json").exists()
    assert (plugin / "hooks" / "dan-compact.mjs").exists()
    assert (plugin / "hooks" / "core.mjs").exists()


def _wire_parallel_job(monkeypatch, tmp_path, compact):
    """parallel_job_runner._launch を DB・プロセス無しで組み立てだけ回す（並行作業も Claude Code を起こす経路）。"""
    from app.services import parallel_job_runner as runner
    from app.services import project_service

    async def no_project(self, room_id):
        return {}

    monkeypatch.setattr(project_service.ProjectService, "__init__", lambda self: None)
    monkeypatch.setattr(project_service.ProjectService, "get_project_by_room_id", no_project)
    monkeypatch.setattr(cr, "_load_session", lambda room_id: None)
    monkeypatch.setattr(cr, "_build_reseed_context", lambda room_id, project_id=None, max_chars=None: "")
    room_mcp = tmp_path / "mcp_room.json"
    room_mcp.write_text('{"mcpServers": {"dan-tools": {}}}', encoding="utf-8")

    async def inputs(*a, **k):
        return "SYS", str(room_mcp)

    monkeypatch.setattr(cr, "_prepare_cli_inputs", inputs)
    monkeypatch.setattr(cr, "_resolve_claude_cli", lambda: ("claude", None))
    monkeypatch.setattr(runner.state, "browser_room", lambda job_id: "browser-room")
    real_path = runner.Path

    def path(p, *rest):   # 作業フォルダ（D:/dan-workspace/jobs/…）は一時フォルダへ
        text = str(p)
        if text.startswith("D:/dan-workspace/jobs/"):
            return real_path(tmp_path) / "jobs" / text.rsplit("/", 1)[1]
        return real_path(p, *rest)

    monkeypatch.setattr(runner, "Path", path)
    calls: list = []

    def launch(user_id, *, log=True):
        calls.append(user_id)
        return compact

    monkeypatch.setattr(cr, "_dan_compact_launch", launch)
    return runner, calls


@pytest.mark.asyncio
async def test_parallel_job_launch_gets_plugin_only_with_key(monkeypatch, tmp_path):
    job = {"room_id": "R", "user_id": "U", "task": "調べて", "model": "opus"}
    runner, calls = _wire_parallel_job(monkeypatch, tmp_path, ([], {}))
    plain_cmd, plain_env, _, _ = await runner._launch("job-0000-aaaa", job)
    assert "--plugin-dir" not in plain_cmd
    assert "TYPESAFE_API_KEY" not in plain_env and "CLAUDE_CODE_ENABLE_FUNCTION_HOOKS" not in plain_env
    assert "--settings" in plain_cmd and plain_cmd[-2:] == ["--input-format", "stream-json"]

    runner, calls = _wire_parallel_job(monkeypatch, tmp_path, (
        ["--plugin-dir", "P"], {"CLAUDE_CODE_ENABLE_FUNCTION_HOOKS": "1", "TYPESAFE_API_KEY": KEY}))
    cmd, env, _, _ = await runner._launch("job-0000-aaaa", job)
    assert calls == ["U"], "部屋の利用者の鍵で判定する"
    assert cmd == plain_cmd[:-2] + ["--plugin-dir", "P", "--input-format", "stream-json"], "他の引数は不変、足すだけ"
    assert env["TYPESAFE_API_KEY"] == KEY and env["CLAUDE_CODE_ENABLE_FUNCTION_HOOKS"] == "1"
    assert env["DAN_COMMAND_JOB_ID"] == "job-0000-aaaa"
    assert {k: v for k, v in env.items() if k not in ("TYPESAFE_API_KEY", "CLAUDE_CODE_ENABLE_FUNCTION_HOOKS")} == plain_env
