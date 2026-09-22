"""Isolated real Codex/Chrome regression proof; never uses production profiles.

Run: python scripts/check_browser_lifecycle.py
The two Codex turns only call a synthetic local diagnostic MCP tool.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def server(proof: Path, port: int):
    from fastapi import FastAPI
    from app.core.api.browser_routes import router
    from app.services import browser_lifecycle as lifecycle
    from app.tools import browser
    import uvicorn

    Path.home = classmethod(lambda cls: proof / "home")
    original_spawn = browser._spawn_detached_browser
    original_popen = subprocess.Popen

    def headless_spawn(*args):
        def popen(argv, **kwargs):
            return original_popen([argv[0], "--headless=new", *argv[1:]], **kwargs)
        with patch.object(browser.subprocess, "Popen", popen):
            return original_spawn(*args)

    browser._spawn_detached_browser = headless_spawn

    @asynccontextmanager
    async def lifespan(app):
        lifecycle.initialize_core()
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(router)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/probe/reap")
    def reap():
        return lifecycle.reap_idle(1800, set())

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def mcp_probe(proof: Path, phase: str):
    from app.tools import browser
    from app.services import browser_lifecycle as lifecycle
    Path.home = classmethod(lambda cls: proof / "home")
    # Browser worker logs must not contaminate the MCP stdio transport.
    protocol_out = sys.stdout
    sys.stdout = sys.stderr

    async def inspect():
        page = await browser.get_executor_page()
        if phase == "first":
            await page.goto((proof / "form.html").as_uri())
            await page.evaluate("window.lifetimeMarker = 'same-live-document'; document.querySelector('input').value = 'before-handoff'")
            await asyncio.to_thread(lifecycle.request_session, "hold", "lifetime-proof", "Waiting for user input")
        result = await page.evaluate("({marker:window.lifetimeMarker,value:document.querySelector('input').value,url:location.href})")
        state = await asyncio.to_thread(lifecycle.request_session, "status", "lifetime-proof")
        result["session"] = state
        (proof / f"{phase}-probe.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        method = request.get("method")
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "lifetime-proof", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "probe_status", "description": "Run the isolated browser lifetime check",
                                  "inputSchema": {"type": "object", "properties": {}}}]}
        elif method == "tools/call":
            try:
                result = {"content": [{"type": "text", "text": json.dumps(asyncio.run(inspect()))}]}
            except Exception:
                import traceback
                error = traceback.format_exc()
                (proof / f"{phase}-error.log").write_text(error, encoding="utf-8")
                result = {"isError": True, "content": [{"type": "text", "text": error}]}
        else:
            result = {}
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), file=protocol_out, flush=True)


def run_proof(proof: Path):
    from app.agent.codex_runner import resolve_codex_cli
    from app.services import browser_lifecycle as lifecycle
    from playwright.sync_api import sync_playwright

    proof.mkdir(parents=True, exist_ok=False)
    (proof / "form.html").write_text('<title>Browser lifetime proof</title><input id="handoff">', encoding="utf-8")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if k not in {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CLAUDECODE"}}
    env.update(DAN_CORE_PORT=str(port), DAN_SESSION_ID="lifetime-proof", PYTHONIOENCODING="utf-8")
    script = str(Path(__file__).resolve())
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    out = (proof / "server.log").open("w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, script, "--role", "server", "--proof", str(proof), "--port", str(port)],
                            env=env, stdout=out, stderr=out, creationflags=flags)

    def request(operation, room="lifetime-proof"):
        with patch.object(Path, "home", return_value=proof / "home"), patch.dict(os.environ, {"DAN_CORE_PORT": str(port)}):
            return lifecycle.request_session(operation, room)

    def age(room):
        with patch.object(Path, "home", return_value=proof / "home"):
            (lifecycle.profile_for_room(room) / "dan_last_use.txt").write_text("1", encoding="utf-8")

    def reap():
        req = urllib.request.Request(f"http://127.0.0.1:{port}/probe/reap", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1):
                    break
            except OSError:
                time.sleep(.2)
        else:
            raise RuntimeError("Test owner did not start")
        summary = {"codex_version": subprocess.check_output([resolve_codex_cli(), "--version"], text=True).strip()}
        for phase in ["first", "second"]:
            args = [script, "--role", "mcp", "--proof", str(proof), "--phase", phase]
            config = ("mcp_servers={lifetime_probe={command=" + json.dumps(sys.executable)
                      + ",args=" + json.dumps(args) + ",required=true,startup_timeout_sec=40,env={DAN_SESSION_ID=\"lifetime-proof\",DAN_CORE_PORT="
                      + json.dumps(str(port)) + ",PYTHONIOENCODING=\"utf-8\"}}}")
            cmd = [resolve_codex_cli(), "exec", "--json", "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox",
                   "-c", config, "-c", 'developer_instructions="Call lifetime_probe probe_status once, then reply OK only. Do not use other tools."', "-m", "gpt-6-astra", "-"]
            with (proof / f"{phase}-codex.jsonl").open("w", encoding="utf-8") as log:
                result = subprocess.run(cmd, input="Call lifetime_probe probe_status once and reply OK. Isolated process lifecycle diagnostic only.",
                                        text=True, cwd=proof, env=env, stdout=log, stderr=subprocess.PIPE, timeout=120, creationflags=flags)
            assert result.returncode == 0, result.stderr
            assert (proof / f"{phase}-probe.json").exists(), "Codex did not call diagnostic tool"
            time.sleep(2)
            state = request("status")
            assert state["alive"] and state["state"] == "held", state
            summary[phase + "_after_cli_exit"] = state
            with sync_playwright() as pw:
                chrome = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{state['port']}")
                page = chrome.contexts[0].pages[-1]
                assert page.evaluate("window.lifetimeMarker") == "same-live-document"
                if phase == "first":
                    page.locator("input").fill("entered-by-user-between-turns")
                else:
                    assert page.locator("input").input_value() == "entered-by-user-between-turns"
                chrome.close()  # Disconnect the test client; leave owner browser alive.
        second = json.loads((proof / "second-probe.json").read_text(encoding="utf-8"))
        assert second["value"] == "entered-by-user-between-turns"
        age("lifetime-proof")
        assert reap() == [], "Held browser was reaped"
        summary["held_survives_idle_cleanup"] = True
        request("ensure", "other-room")
        request("hold", "other-room")
        request("release")
        assert request("status")["alive"], "Release closed the page"
        age("lifetime-proof")
        assert len(reap()) == 1
        assert not request("status")["alive"]
        assert request("status", "other-room")["alive"]
        summary["released_browser_reaped_other_room_preserved"] = True
        (proof / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2))
    finally:
        for room in ["lifetime-proof", "other-room"]:
            try:
                request("close", room)
            except Exception:
                pass
        proc.terminate()
        proc.wait(timeout=10)
        out.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["run", "server", "mcp"], default="run")
    parser.add_argument("--proof", type=Path, default=ROOT / "scratch" / f"browser-lifecycle-proof-{int(time.time())}")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--phase", default="first")
    args = parser.parse_args()
    proof = args.proof.resolve()
    if args.role == "server":
        server(proof, args.port)
    elif args.role == "mcp":
        mcp_probe(proof, args.phase)
    else:
        run_proof(proof)
