import asyncio
import json
import queue
import threading
from unittest.mock import AsyncMock

import pytest
from playwright.async_api import async_playwright

from app.tools import browser
from app.tools.browser_actions import fill_form, wait_for_condition


@pytest.fixture(autouse=True)
def isolated_metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("DAN_BROWSER_TIMING_LOG", str(tmp_path / "browser-timing.jsonl"))


def run_browser(check):
    async def run():
        async with async_playwright() as pw:
            instance = await pw.chromium.launch()
            try:
                page = await instance.new_page()
                await check(page)
            finally:
                await instance.close()
    asyncio.run(run())


FORM = '<input data-dan-ref="e1"><input data-dan-ref="e2"><button onclick="window.submitted=true">Submit</button>'
FIELDS = [{"ref": "@e1", "value": "Alice"}, {"ref": "@e2", "value": "Tokyo"}]


def test_fill_verifies_values_and_never_submits():
    async def check(page):
        await page.set_content(FORM)
        result = await fill_form(page, FIELDS, page.url)
        assert result["success"] and result["verified"]
        assert await page.locator("input").evaluate_all("els => els.map(e => e.value)") == ["Alice", "Tokyo"]
        assert not await page.evaluate("!!window.submitted")
    run_browser(check)


@pytest.mark.parametrize("html,fields", [
    (FORM, [FIELDS[0], {"ref": "@e9", "value": "missing"}]),
    (FORM.replace('data-dan-ref="e2"', 'data-dan-ref="e1"'), FIELDS),
    (FORM.replace('<input data-dan-ref="e2">', '<input data-dan-ref="e2" disabled>'), FIELDS),
    (FORM.replace('<input data-dan-ref="e2">', '<input data-dan-ref="e2" type="password">'), FIELDS),
])
def test_preflight_failure_does_not_fill_first_field(html, fields):
    async def check(page):
        await page.set_content(html)
        result = await fill_form(page, fields, page.url)
        assert not result["success"] and not result["completed_refs"]
        assert await page.locator("input").first.input_value() == ""
    run_browser(check)


def test_rerender_stops_before_writing_replacement_field():
    async def check(page):
        await page.set_content(FORM)
        await page.evaluate("""() => document.querySelector('input').addEventListener('input', () => {
          document.querySelectorAll('input')[1].outerHTML = '<input data-dan-ref="e2" value="replacement">';
        })""")
        result = await fill_form(page, FIELDS, page.url)
        assert not result["success"] and not result["retry_safe"]
        assert await page.locator("input").nth(1).input_value() == "replacement"
    run_browser(check)


def test_later_input_modifying_earlier_value_fails_final_verification():
    async def check(page):
        await page.set_content(FORM)
        await page.evaluate("""() => document.querySelectorAll('input')[1].addEventListener('input', () => {
          document.querySelector('input').value = 'unexpected';
        })""")
        result = await fill_form(page, FIELDS, page.url)
        assert not result["success"] and result["stage"] == "verify"
    run_browser(check)


def test_cancelled_batch_and_wrong_url_never_write():
    async def check(page):
        await page.set_content(FORM)
        cancelled = threading.Event()
        cancelled.set()
        result = await fill_form(page, FIELDS, page.url, cancelled)
        assert not result["success"] and not result["completed_refs"]
        with pytest.raises(ValueError):
            await fill_form(page, FIELDS, "https://wrong.invalid")
        assert await page.locator("input").first.input_value() == ""
    run_browser(check)


def test_delayed_result_and_hidden_condition_are_verified():
    async def check(page):
        await page.set_content('<div id="result">Loading</div>')
        await page.evaluate("setTimeout(() => document.querySelector('#result').textContent = 'Saved', 200)")
        result = await wait_for_condition(page, {"selector": "#result", "text": "Saved", "timeout_ms": 2000})
        assert result["verified"]
        await page.evaluate("document.querySelector('#result').remove()")
        assert (await wait_for_condition(page, {"selector": "#result", "state": "hidden"}))["verified"]
    run_browser(check)


def test_click_does_not_force_through_overlay():
    async def check(page):
        await page.set_content('<button data-dan-ref="e1" onclick="window.clicked=true">OK</button><div style="position:fixed;inset:0;background:white"></div>')
        with pytest.raises(Exception):
            await browser._execute_page_command({"current": page}, page.context, "click_by_ref", {"ref": "@e1", "timeout": 150})
        assert not await page.evaluate("!!window.clicked")
    run_browser(check)


def test_observation_refs_follow_elements_not_list_positions():
    async def check(page):
        await page.set_content('<input id="first"><input id="second">')
        async def elements():
            return (await browser._execute_page_command({"current": page}, page.context, "get_interactive_elements", {}))["elements"]
        before = {e["id"]: e["ref"] for e in await elements()}
        await page.evaluate("document.querySelector('#first').remove(); document.body.insertAdjacentHTML('afterbegin', '<input id=third>')")
        after = {e["id"]: e["ref"] for e in await elements()}
        assert before["second"] == after["second"]
        assert before["first"] not in after.values()
    run_browser(check)


def test_popup_still_switches_with_default_click_path(monkeypatch):
    from app.agent.v2 import tools
    async def check(page):
        await page.set_content('<a data-dan-ref="e1" href="about:blank#popup" target="_blank">Open</a>')
        state = {"current": page, "all_pages": [page]}
        page.context.on("page", lambda p: state["all_pages"].append(p))
        await browser._execute_page_command(state, page.context, "click_by_ref", {"ref": "@e1"})
        # Existing fallback path permits a popup event to arrive.
        await page.wait_for_timeout(500)
        result = await browser._execute_page_command(state, page.context, "switch_to_latest_tab", {})
        assert result["switched"] and result["url"].endswith("#popup")
    run_browser(check)


def test_batch_stops_when_input_navigates():
    async def check(page):
        await page.set_content(FORM)
        await page.evaluate("document.querySelector('input').addEventListener('input', () => location.hash='changed')")
        result = await fill_form(page, FIELDS, page.url)
        assert not result["success"]
        assert await page.locator("input").nth(1).input_value() == ""
    run_browser(check)


def test_reply_queues_are_isolated_when_results_arrive_out_of_order(monkeypatch):
    monkeypatch.setattr(browser, "_ensure_executor_thread", lambda: None)
    monkeypatch.setattr(browser, "_touch_browser_activity", lambda: None)
    commands = queue.Queue()
    monkeypatch.setattr(browser, "_executor_command_queue", commands)
    results = {}
    def call(name):
        results[name] = browser._send_executor_command(name)
    first = threading.Thread(target=call, args=("get_url",))
    second = threading.Thread(target=call, args=("get_tab_count",))
    first.start()
    cmd1 = commands.get(timeout=2)
    second.start()
    cmd2 = commands.get(timeout=2)
    cmd2[2]["reply"].put(("success", {"owner": cmd2[0]}))
    cmd1[2]["reply"].put(("success", {"owner": cmd1[0]}))
    first.join(2)
    second.join(2)
    assert results == {"get_url": {"owner": "get_url"}, "get_tab_count": {"owner": "get_tab_count"}}


def test_closed_browser_does_not_replay_mutation(monkeypatch):
    monkeypatch.setattr(browser, "_ensure_executor_thread", lambda: None)
    monkeypatch.setattr(browser, "_touch_browser_activity", lambda: None)
    class Commands:
        count = 0
        def put(self, command):
            self.count += 1
            command[2]["reply"].put(("browser_closed", "closed"))
    commands = Commands()
    monkeypatch.setattr(browser, "_executor_command_queue", commands)
    with pytest.raises(RuntimeError, match="outcome is unknown"):
        browser._send_executor_command("click_by_ref", ref="@e1")
    assert commands.count == 1


def test_tool_dispatch_batch_returns_single_full_observation(monkeypatch):
    from app.agent.v2 import tools
    page = AsyncMock()
    page.fill_form.return_value = {"success": True, "verified": True}
    monkeypatch.setattr(browser, "get_executor_page", AsyncMock(return_value=page))
    observe = AsyncMock(return_value={"success": True, "content": [{"type": "image"}, {"type": "text", "text": "state"}]})
    monkeypatch.setattr(tools, "_get_browser_state", observe)
    result = asyncio.run(tools._execute_browser_tool("fill_form", {"fields": FIELDS, "expected_url": "about:blank"}))
    assert result["verified"] and any(item["type"] == "image" for item in result["content"])
    observe.assert_awaited_once()
    assert "fill_form" in tools.BROWSER_TOOL["input_schema"]["properties"]["action"]["enum"]


def test_failed_condition_returns_screen_without_replaying(monkeypatch):
    from app.agent.v2 import tools
    page = AsyncMock()
    page.wait_for_condition.side_effect = RuntimeError("timeout")
    monkeypatch.setattr(tools, "_get_browser_state", AsyncMock(return_value={"success": True, "content": []}))
    result = asyncio.run(tools._browser_expect_state(page, {"selector": "#result"}))
    assert not result["success"] and not result["condition_verified"]
    page.click_by_ref.assert_not_called()


def test_postcondition_preflight_rejects_already_true_or_ambiguous_evidence():
    from app.tools.browser_actions import check_condition_before_action
    async def check(page):
        await page.set_content('<p id="result">Saved</p><p>Other</p>')
        with pytest.raises(ValueError, match="already true"):
            await check_condition_before_action(page, {"selector": "#result", "text": "Saved"})
        with pytest.raises(ValueError, match="ambiguous"):
            await check_condition_before_action(page, {"selector": "p"})
        assert (await check_condition_before_action(page, {"selector": "#result", "text": "Updated"}))["ready"]
    run_browser(check)


def test_invalid_condition_cannot_trigger_click(monkeypatch):
    from app.agent.v2 import tools
    page = AsyncMock()
    monkeypatch.setattr(browser, "get_executor_page", AsyncMock(return_value=page))
    result = asyncio.run(tools._execute_browser_tool("click", {"ref": "@e1", "expect": {"selector": "#result", "timeout_ms": -1}}))
    assert not result["success"]
    page.click_by_ref.assert_not_called()


def test_metrics_do_not_record_form_contents(tmp_path, monkeypatch):
    from app.tools.browser_metrics import record_timing
    path = tmp_path / "timing.jsonl"
    monkeypatch.setenv("DAN_BROWSER_TIMING_LOG", str(path))
    monkeypatch.setenv("DAN_BROWSER_METRICS", "1")
    record_timing("execution", "fill_form", 12.34)
    event = json.loads(path.read_text())
    assert set(event) == {"time", "pid", "phase", "operation", "elapsed_ms", "status"}


def test_guarded_click_recovers_clear_edge_without_clicking_overlay():
    from app.tools.browser_actions import guarded_click
    async def check(page):
        await page.set_content('''<button data-dan-ref="e1" style="position:absolute;left:0;top:0;width:200px;height:100px"
            onclick="window.clicked=(window.clicked||0)+1">Next</button>
            <div style="position:absolute;left:80px;top:0;width:40px;height:100px;background:red"
            onclick="window.wrong=true"></div>''')
        result = await guarded_click(page, "@e1", timeout=2500)
        assert result["success"] and result["recovered_clear_point"]
        assert await page.evaluate("window.clicked") == 1
        assert not await page.evaluate("!!window.wrong")
    run_browser(check)


def test_guarded_click_explains_fully_occluded_target_without_dispatch():
    from app.tools.browser_actions import guarded_click
    async def check(page):
        await page.set_content('<button data-dan-ref="e1" onclick="window.clicked=true">Buy</button><div id="dialog" role="dialog" style="position:fixed;inset:0;background:white"></div>')
        result = await guarded_click(page, "@e1", timeout=1500)
        assert not result["success"] and result["dispatched"] is False
        assert result["reason"] == "occluded" and result["blocker"]["id"] == "dialog"
        assert "Dismiss" in result["next_action"]
        assert not await page.evaluate("!!window.clicked")
    run_browser(check)


def test_guarded_click_waits_for_transient_overlay():
    from app.tools.browser_actions import guarded_click
    async def check(page):
        await page.set_content('<button data-dan-ref="e1" onclick="window.clicked=(window.clicked||0)+1">Next</button><div id="overlay" style="position:fixed;inset:0;background:white"></div>')
        await page.evaluate("setTimeout(() => document.querySelector('#overlay').remove(), 100)")
        result = await guarded_click(page, "@e1", timeout=2000)
        assert result["success"]
        assert await page.evaluate("window.clicked") == 1
    run_browser(check)


def test_guarded_click_never_retries_after_possible_dispatch():
    from app.tools.browser_actions import guarded_click
    async def check():
        handle = AsyncMock()
        handle.is_visible.return_value = True
        handle.is_enabled.return_value = True
        handle.click.side_effect = [None, RuntimeError("navigation failed after dispatch")]
        target = AsyncMock()
        target.count.return_value = 1
        target.element_handle.return_value = handle
        class Page:
            def locator(self, selector):
                return target
        result = await guarded_click(Page(), "@e1")
        assert result["reason"] == "click_outcome_unknown" and result["dispatched"] is None
        assert handle.click.await_count == 2  # one trial + one real click, no replay
    asyncio.run(check())


def test_compact_refs_change_on_navigation_and_remain_usable():
    from app.tools.browser_actions import ref_selector, guarded_click
    async def check(page):
        async def read_ref():
            result = await browser._execute_page_command({"current": page}, page.context, "get_interactive_elements", {})
            return result["elements"][0]["ref"]
        await page.goto('data:text/html,<button onclick="window.clicked=true">First</button>')
        old = await read_ref()
        assert len(old) <= 12
        await page.goto('data:text/html,<button onclick="window.clicked=true">Second</button>')
        new = await read_ref()
        assert old != new and await page.locator(ref_selector(old)).count() == 0
        assert (await guarded_click(page, new))["success"]
        assert await page.evaluate("window.clicked")
    run_browser(check)


def test_click_diagnosis_reaches_model_with_screen(monkeypatch):
    from app.agent.v2 import tools
    page = AsyncMock()
    page.get_tab_count.return_value = {"count": 1}
    page.guarded_click.return_value = {"success": False, "reason": "occluded", "dispatched": False, "next_action": "Inspect dialog"}
    monkeypatch.setattr(browser, "get_executor_page", AsyncMock(return_value=page))
    monkeypatch.setattr(tools, "_get_browser_state", AsyncMock(return_value={"success": True, "content": [{"type": "image"}]}))
    result = asyncio.run(tools._execute_browser_tool("click", {"ref": "@e1"}))
    assert not result["success"] and result["reason"] == "occluded"
    assert "Inspect dialog" in result["content"][0]["text"]
    assert result["content"][1]["type"] == "image"


def test_cancel_after_click_trial_prevents_dispatch():
    from app.tools.browser_actions import guarded_click
    async def check():
        cancelled = threading.Event()
        handle = AsyncMock()
        handle.is_visible.return_value = handle.is_enabled.return_value = True
        async def trial(**kwargs): cancelled.set()
        handle.click.side_effect = trial
        target = AsyncMock()
        target.count.return_value = 1
        target.element_handle.return_value = handle
        class Page:
            def locator(self, selector): return target
        result = await guarded_click(Page(), "@e1", cancelled=cancelled)
        assert result["reason"] == "cancelled" and result["dispatched"] is False
        handle.click.assert_awaited_once()
    asyncio.run(check())


def test_request_metric_preserves_events_and_closes_underlying_generator(tmp_path):
    from app.tools.browser_metrics import measure_browser_request
    events = [{"type": "tool_use", "name": "mcp__dan__browser", "input": {"text": "private-value"}}, {"type": "result", "is_error": False}]
    closed = []
    @measure_browser_request
    async def stream():
        try:
            for event in events: yield event
        finally: closed.append(True)
    async def check():
        assert [event async for event in stream()] == events
        generator = stream()
        await anext(generator)
        await generator.aclose()
    asyncio.run(check())
    assert len(closed) == 2
    text = (tmp_path / "browser-timing.jsonl").read_text()
    rows = [json.loads(line) for line in text.splitlines()]
    assert [row["status"] for row in rows] == ["returned", "interrupted"]
    assert all(row["browser_calls"] == 1 for row in rows)
    assert "private-value" not in text


def test_command_cancellation_observes_session_event():
    session_event = threading.Event()
    signal = browser._CommandCancellation(session_event)
    assert not signal.is_set()
    session_event.set()
    assert signal.is_set()
