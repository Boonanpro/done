"""Real Claude + production browser-tool benchmark on an isolated local form.

No simulated reasoning delays. No user profiles, accounts, or external actions.
Run: python scripts/benchmark_browser_agent.py --rounds 2
"""
import argparse
import asyncio
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def repeated_field_requests(messages):
    seen_calls, seen_fields = set(), set()
    repeats = 0
    for message in messages:
        if message.get("type") != "assistant": continue
        for block in message.get("message", {}).get("content", []):
            if block.get("type") != "tool_use" or block.get("id") in seen_calls: continue
            seen_calls.add(block.get("id"))
            args = block.get("input", {})
            refs = [args.get("ref")] if args.get("action") == "type" else [f.get("ref") for f in args.get("fields", [])]
            for ref in refs:
                if ref in seen_fields: repeats += 1
                seen_fields.add(ref)
    return repeats


async def serve(run_dir, mode):
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    import mcp.types as types
    from playwright.async_api import async_playwright
    from app.tools import browser
    from app.agent.v2 import tools

    app = Server("browser_benchmark")
    async with async_playwright() as pw:
        instance = await pw.chromium.launch()
        page = await instance.new_page()
        state = {"current": page, "all_pages": [page]}
        lock = asyncio.Lock()

        async def command(name, **args):
            return await browser._execute_page_command(state, page.context, name, args)

        class Proxy:
            @property
            def url(self): return page.url
            async def goto(self, url): return await command("goto", url=url)
            async def wait_for_load_state(self, *a, **kw): return await page.wait_for_load_state(*a, **kw)
            async def wait_for_timeout(self, value): return await page.wait_for_timeout(value)
            async def screenshot_base64(self, **kw): return await command("screenshot_base64", **kw)
            async def get_interactive_elements(self): return (await command("get_interactive_elements"))["elements"]
            async def get_page_context(self): return (await command("get_page_context"))["context"]
            async def evaluate(self, expression): return await page.evaluate(expression)
            async def fill_by_ref(self, ref, value): return await command("fill_by_ref", ref=ref, value=value)
            async def fill_form(self, fields, expected_url): return await command("fill_form", fields=fields, expected_url=expected_url)

        proxy = Proxy()
        async def get_page(): return proxy
        browser.get_executor_page = get_page
        schema = copy.deepcopy(tools.BROWSER_TOOL)
        allowed = {"open", "screenshot", "type"}
        if mode == "optimized": allowed.add("fill_form")
        props = schema["input_schema"]["properties"]
        props["action"]["enum"] = sorted(allowed)
        keep = {"action", "url", "ref", "text"}
        if mode == "optimized": keep |= {"fields", "expected_url"}
        schema["input_schema"]["properties"] = {k: v for k, v in props.items() if k in keep}
        schema["description"] = "Operate the browser. Every action returns a screenshot and current page elements. Verify the result before reporting completion."
        if mode == "optimized":
            schema["description"] += " Use fill_form for already observed independent text fields; it verifies each value and the final form in one call. It does not submit."

        @app.list_tools()
        async def list_tools():
            return [types.Tool(name="browser", description=schema["description"], inputSchema=schema["input_schema"])]

        @app.call_tool()
        async def call_tool(name, arguments):
            async with lock:
                started = time.perf_counter()
                action = arguments.get("action")
                if (name != "browser" or action not in allowed or set(arguments) - keep or
                        (action == "open" and arguments.get("url") != (run_dir / "fixture.html").as_uri())):
                    return [types.TextContent(type="text", text="Unsupported benchmark action")]
                result = await tools._execute_browser_tool(action, arguments)
                values = await page.locator("input").evaluate_all("els => els.map(el => el.value)")
                verified = values == [f"Sample {i}" for i in range(8)]
                with (run_dir / "events.jsonl").open("a", encoding="utf-8") as out:
                    out.write(json.dumps({"action": action, "elapsed_ms": (time.perf_counter()-started)*1000,
                                          "success": bool(result.get("success")), "form_verified": verified}) + "\n")
                content = []
                for item in result.get("content", []):
                    if item["type"] == "image":
                        content.append(types.ImageContent(type="image", data=item["source"]["data"], mimeType=item["source"]["media_type"]))
                    elif item["type"] == "text": content.append(types.TextContent(type="text", text=item["text"]))
                return content or [types.TextContent(type="text", text=str(result.get("error", "No result")))]

        try:
            async with stdio_server() as (read, write):
                await app.run(read, write, app.create_initialization_options())
        finally:
            await instance.close()


def run_benchmark(output, rounds, model):
    output.mkdir(parents=True, exist_ok=True)
    runs = []
    cli = shutil.which("claude")
    if not cli: raise RuntimeError("Claude CLI is required")
    for repetition in range(rounds):
        for mode in (["individual", "optimized"] if repetition % 2 == 0 else ["optimized", "individual"]):
            run_dir = Path(tempfile.mkdtemp(prefix=f"dan-browser-bench-{mode}-"))
            (run_dir / "fixture.html").write_text('<h1>Benchmark contact form</h1>' + ''.join(f'<label>Field {i}<input id="f{i}"></label><br>' for i in range(8)), encoding="utf-8")
            config = {"mcpServers": {"browser_benchmark": {"command": sys.executable,
                "args": [str(Path(__file__).resolve()), "--server", "--mode", mode, "--output", str(run_dir)],
                "env": {"DAN_BROWSER_TIMING_LOG": str(run_dir / "timings.jsonl")}}}}
            (run_dir / "mcp.json").write_text(json.dumps(config), encoding="utf-8")
            task = f"Open {(run_dir/'fixture.html').as_uri()}. Fill Field 0 through Field 7 with Sample 0 through Sample 7 respectively. Verify all eight values. Do not submit. When done, reply briefly."
            args = [cli, "--print", "--setting-sources", "", "--no-session-persistence", "--model", model,
                    "--strict-mcp-config", "--mcp-config", str(run_dir / "mcp.json"),
                    "--tools", "", "--allowedTools", "mcp__browser_benchmark__browser",
                    "--max-budget-usd", "2", "--output-format", "stream-json", "--verbose",
                    "--system-prompt", "Complete the user's browser task using the available browser tool. Use only observed refs. Verify the final result. Do not request permission for these local test inputs.", task]
            started = time.perf_counter()
            proc = subprocess.run(args, cwd=run_dir, capture_output=True, text=True, encoding="utf-8", timeout=240,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            wall = time.perf_counter() - started
            (run_dir / "transcript.jsonl").write_text(proc.stdout, encoding="utf-8")
            (run_dir / "stderr.txt").write_text(proc.stderr, encoding="utf-8")
            messages = []
            for line in proc.stdout.splitlines():
                try: messages.append(json.loads(line))
                except ValueError: pass
            events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()] if (run_dir / "events.jsonl").exists() else []
            finals = [m for m in messages if m.get("type") == "result"]
            final = finals[-1] if finals else {}
            resolved_model = next((m.get("model") for m in messages if m.get("type") == "system" and m.get("subtype") == "init"), None)
            assistant_turns = {m.get("message", {}).get("id") for m in messages if m.get("type") == "assistant"}
            row = {"mode": mode, "repetition": repetition, "model": model, "resolved_model": resolved_model, "wall_seconds": round(wall, 2),
                   "completed": bool(events and events[-1]["form_verified"] and not final.get("is_error", True)),
                   "tool_calls": len(events), "failed_tool_calls": sum(not e["success"] for e in events),
                   "repeated_field_requests": repeated_field_requests(messages),
                   "assistant_messages": len(assistant_turns), "tool_seconds": round(sum(e["elapsed_ms"] for e in events)/1000, 2),
                   "exit_code": proc.returncode, "cost_usd_reported": final.get("total_cost_usd"),
                   "actions": [e["action"] for e in events]}
            runs.append(row)
            shutil.copytree(run_dir, output / f"{repetition}-{mode}", dirs_exist_ok=True)
            print(json.dumps(row), flush=True)
            (output / "summary.json").write_text(json.dumps({"scope": "Real Claude CLI + production browser dispatch on isolated local fixture. Wall time includes startup/model/tool/network. Not a production Dan conversation or external-site task.", "runs": runs}, indent=2), encoding="utf-8")
            if not events:
                raise RuntimeError("Agent did not reach browser tool; see isolated transcript/stderr. No performance claim possible.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", action="store_true")
    parser.add_argument("--mode", choices=["individual", "optimized"], default="optimized")
    parser.add_argument("--output", type=Path, default=ROOT / "scratch/browser-agent-benchmark")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--model", default="sonnet")
    args = parser.parse_args()
    if args.server: asyncio.run(serve(args.output.resolve(), args.mode))
    else: run_benchmark(args.output.resolve(), args.rounds, args.model)
