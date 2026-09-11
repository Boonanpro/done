"""Isolated Chromium benchmark: real browser work, no user accounts or LLM fees.

Run: python scripts/benchmark_browser_actions.py --output scratch/browser-benchmark.json
"""
import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright
from app.tools.browser import _execute_page_command


async def benchmark(rounds=5, field_count=8):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        state = {"current": page, "all_pages": [page]}
        async def command(name, **args):
            return await _execute_page_command(state, page.context, name, args)
        async def observe():
            # The production observation path captures all three after input.
            await command("screenshot_base64", full_page=False)
            elements = await command("get_interactive_elements")
            await command("get_page_context")
            return elements["elements"]
        samples = {"individual": [], "verified_batch": []}
        html = '<h1>Contact details</h1>' + ''.join(f'<label>Field {i}<input id="f{i}"></label><br>' for i in range(field_count))
        html += '<button onclick="window.submissions=(window.submissions||0)+1">Submit</button>'
        try:
            for repetition in range(rounds + 1):
                # Warm both paths once and alternate order to limit warm-cache bias.
                order = list(samples) if repetition % 2 else list(reversed(samples))
                for mode in order:
                    await page.set_content(html)
                    elements = await observe()
                    fields = [{"ref": next(e["ref"] for e in elements if e["id"] == f"f{i}"), "value": f"Sample {i}"} for i in range(field_count)]
                    started = time.perf_counter()
                    if mode == "individual":
                        for field in fields:
                            await command("fill_by_ref", ref=field["ref"], value=field["value"])
                            await observe()
                    else:
                        result = await command("fill_form", fields=fields, expected_url=page.url)
                        assert result["success"], result
                        await observe()
                    elapsed = (time.perf_counter() - started) * 1000
                    assert await page.locator("input").evaluate_all("els => els.map(e => e.value)") == [f"Sample {i}" for i in range(field_count)]
                    assert await page.evaluate("window.submissions || 0") == 0
                    if repetition:
                        samples[mode].append(round(elapsed, 2))
            # Same click/result; fixed 500 ms versus explicit result evidence.
            click_samples = {"fixed_500ms": [], "condition": []}
            for mode in click_samples:
                for _ in range(rounds):
                    await page.set_content('<button data-dan-ref="e1" onclick="document.querySelector(\'#result\').textContent=\'Saved\'">Save</button><p id="result">Ready</p>')
                    started = time.perf_counter()
                    if mode == "condition":
                        await command("check_condition_before_action", condition={"selector": "#result", "text": "Saved"})
                    outcome = await command("guarded_click", ref="@e1", timeout=1000)
                    assert outcome["success"], outcome
                    if mode == "fixed_500ms":
                        await page.wait_for_timeout(500)
                    else:
                        await command("wait_for_condition", condition={"selector": "#result", "text": "Saved"})
                    await observe()
                    assert await page.locator("#result").inner_text() == "Saved"
                    click_samples[mode].append(round((time.perf_counter() - started) * 1000, 2))
            medians = {name: round(statistics.median(values), 2) for name, values in samples.items()}
            return {"browser": browser.version, "rounds": rounds, "fields": field_count,
                    "scope": "Local fixture; browser execution + observations only. No LLM/network latency simulated.",
                    "form_samples_ms": samples, "form_median_ms": medians,
                    "form_speedup": round(medians["individual"] / medians["verified_batch"], 2),
                    "tool_calls_individual": field_count, "tool_calls_batch": 1,
                    "click_samples_ms": click_samples,
                    "click_median_ms": {k: round(statistics.median(v), 2) for k, v in click_samples.items()},
                    "validation": "All values match; zero submissions; click results verified on both paths."}
        finally:
            await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="scratch/browser-benchmark.json")
    args = parser.parse_args()
    result = asyncio.run(benchmark())
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
