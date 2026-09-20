"""Verified browser operations. No LLM calls and no blind delay/replay."""

import re
import time

from playwright.async_api import expect


def ref_selector(ref):
    if not isinstance(ref, str) or not re.fullmatch(r"@?(?:e[0-9]+|[A-Za-z0-9_-]{8}:[0-9a-z]+)", ref):
        raise ValueError("Invalid element reference; take a fresh screenshot")
    return f'[data-dan-ref="{ref.lstrip("@")}"]'


async def guarded_click(page, ref, timeout=10000, cancelled=None):
    """Inspect before dispatch. Never retry after a real click was attempted."""
    target = page.locator(ref_selector(ref))
    if await target.count() != 1:
        return {"success": False, "reason": "stale_or_ambiguous_ref", "dispatched": False,
                "next_action": "Inspect the current screen and use its current ref."}
    handle = await target.element_handle(timeout=min(timeout, 1000))
    if handle is None:
        return {"success": False, "reason": "stale_ref", "dispatched": False,
                "next_action": "Inspect the current screen and use its current ref."}
    started = time.perf_counter()
    def remaining():
        return max(1, timeout - int((time.perf_counter() - started) * 1000))
    try:
        if cancelled and cancelled.is_set():
            return {"success": False, "reason": "cancelled", "dispatched": False}
        if not await handle.is_visible() or not await handle.is_enabled():
            return {"success": False, "reason": "not_actionable", "dispatched": False,
                    "next_action": "Wait for the target to become visible/enabled or inspect the page."}
        position = None
        try:
            # Trial checks may scroll, but cannot emit a click or submit a form.
            await handle.click(trial=True, timeout=min(1000, remaining()))
        except Exception:
            # Styled checkboxes/radios sit under their own <label>. The label is
            # the control a person clicks; it is not a foreign overlay.
            label = None
            try:
                label = (await handle.evaluate_handle("""el => {
                    if (!(el instanceof HTMLInputElement) || !['checkbox','radio'].includes(el.type) || !el.labels) return null;
                    const r = el.getBoundingClientRect();
                    const hit = document.elementFromPoint(r.left + r.width/2, r.top + r.height/2);
                    return [...el.labels].find(l => hit && (l === hit || l.contains(hit))) || null;
                }""")).as_element()
            except Exception:
                label = None
            if label is not None:
                try:
                    try:
                        await label.click(trial=True, timeout=min(1000, remaining()))
                    except Exception:
                        label_clear = False  # the label itself is covered: fall through to the overlay diagnosis
                    else:
                        label_clear = True
                    if label_clear:
                        if cancelled and cancelled.is_set():
                            return {"success": False, "reason": "cancelled", "dispatched": False}
                        try:
                            await label.click(timeout=remaining())
                        except Exception:
                            return {"success": False, "reason": "click_outcome_unknown", "dispatched": None,
                                    "next_action": "The label click may already have happened. Inspect the checkbox state; do not repeat blindly."}
                        return {"success": True, "dispatched": True, "via_label": True}
                finally:
                    await label.dispose()
            try:
                probe = await handle.evaluate("""el => {
                    if (!el.isConnected) return {reason: 'stale_ref'};
                    const r = el.getBoundingClientRect();
                    const points = [[.5,.5],[.2,.5],[.8,.5],[.5,.2],[.5,.8],[.2,.2],[.8,.8]];
                    let blocker = null;
                    for (const [fx,fy] of points) {
                        const x = r.left + r.width*fx, y = r.top + r.height*fy;
                        if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue;
                        let hit = document.elementFromPoint(x,y);
                        // elementFromPoint stops at a shadow host; the target may be inside it.
                        while (hit && hit.shadowRoot) {
                            const inner = hit.shadowRoot.elementFromPoint(x,y);
                            if (!inner || inner === hit) break;
                            hit = inner;
                        }
                        if (hit && (hit === el || el.contains(hit))) {
                            const s = getComputedStyle(el);
                            return {position: {x: r.width*fx-parseFloat(s.borderLeftWidth||0),
                                               y: r.height*fy-parseFloat(s.borderTopWidth||0)}};
                        }
                        if (!blocker && hit) blocker = {tag:hit.tagName.toLowerCase(),
                            role:hit.getAttribute('role') || '', id:hit.id || ''};
                    }
                    return {reason:'occluded', blocker};
                }""")
            except Exception:
                probe = {"reason": "inspection_failed"}
            position = probe.get("position")
            if position is None:
                return {"success": False, "dispatched": False, **probe,
                        "next_action": "Inspect the screenshot for a covering dialog/banner. Dismiss it if appropriate, or wait for it to disappear. Do not force-click through it. Use human_click/coordinates only after visually confirming an unobstructed target."}
            try:
                # A corner may be clear even when a carousel overlay covers the
                # center. Check that exact point, with normal actionability.
                await handle.click(position=position, trial=True, timeout=min(1000, remaining()))
            except Exception:
                return {"success": False, "reason": "unstable_or_occluded", "dispatched": False,
                        "next_action": "The candidate point is not reliably clickable. Inspect the screen or wait; do not blindly repeat."}
        try:
            if cancelled and cancelled.is_set():
                return {"success": False, "reason": "cancelled", "dispatched": False}
            await handle.click(position=position, timeout=remaining())
        except Exception:
            return {"success": False, "reason": "click_outcome_unknown", "dispatched": None,
                    "next_action": "The click may already have happened. Inspect the result or use wait_for; do not repeat a submission."}
        return {"success": True, "dispatched": True, "recovered_clear_point": position is not None}
    finally:
        try:
            await handle.dispose()
        except Exception:
            pass


def validate_condition(condition):
    if not isinstance(condition, dict):
        raise ValueError("expect must be an object")
    if set(condition) - {"selector", "state", "text", "timeout_ms"}:
        raise ValueError("Unknown expectation field")
    if not isinstance(condition.get("selector"), str) or not condition["selector"].strip():
        raise ValueError("expect.selector is required")
    if condition.get("state", "visible") not in {"visible", "hidden"}:
        raise ValueError("expect.state must be visible or hidden")
    if "text" in condition and (not isinstance(condition["text"], str) or condition.get("state") == "hidden"):
        raise ValueError("expect.text requires a visible element and a string")
    timeout = condition.get("timeout_ms", 10000)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 30000:
        raise ValueError("expect.timeout_ms must be 1..30000")


async def wait_for_condition(page, condition):
    """Wait for explicit evidence, never infer business success from DOM quiet."""
    validate_condition(condition)
    started = time.perf_counter()
    timeout = condition.get("timeout_ms", 10000)
    target = page.locator(condition["selector"])
    await target.wait_for(state=condition.get("state", "visible"), timeout=timeout)
    if "text" in condition:
        remaining = max(1, timeout - int((time.perf_counter() - started) * 1000))
        await expect(target).to_have_text(condition["text"], timeout=remaining)
    return {"verified": True, "wait_ms": round((time.perf_counter() - started) * 1000, 2)}


async def check_condition_before_action(page, condition):
    """An already-true condition cannot establish the effect of a new action."""
    validate_condition(condition)
    target = page.locator(condition["selector"])
    count = await target.count()  # Also validate selector syntax before acting.
    if count > 1:
        raise ValueError("Expected result selector is ambiguous")
    visible = count == 1 and await target.is_visible()
    satisfied = not visible if condition.get("state") == "hidden" else visible
    if satisfied and "text" in condition:
        normalize = lambda value: " ".join(value.split())
        satisfied = normalize(await target.text_content() or "") == normalize(condition["text"])
    if satisfied:
        raise ValueError("Expected condition is already true; choose evidence of the new action")
    return {"ready": True}


async def fill_form(page, fields, expected_url, cancelled=None):
    """Fill already observed fields, verify identity and values, never submit.

    A partial failure is reported, not rolled back/replayed: input handlers can
    have side effects. Keep element handles so replacement DOM cannot silently
    retarget a later field to a different element carrying an old ref.
    """
    if not isinstance(fields, list) or not 1 <= len(fields) <= 20:
        raise ValueError("fields must contain 1..20 entries")
    if not isinstance(expected_url, str) or page.url != expected_url:
        raise ValueError("Page changed; inspect the current page before filling")
    refs = set()
    for field in fields:
        if not isinstance(field, dict) or set(field) != {"ref", "value"}:
            raise ValueError("Each field requires only ref and value")
        selector = ref_selector(field["ref"])
        if selector in refs or not isinstance(field["value"], str):
            raise ValueError("Duplicate reference or non-string value")
        refs.add(selector)

    handles = []
    completed = []
    attempted = None
    stage = "preflight"
    try:
        for field in fields:
            locator = page.locator(ref_selector(field["ref"]))
            if await locator.count() != 1:
                raise ValueError("Missing or ambiguous field; inspect the page")
            handle = await locator.element_handle()
            handles.append(handle)
            kind = await handle.evaluate("el => ({tag: el.tagName, type: el.type})")
            if kind["tag"] not in {"INPUT", "TEXTAREA"} or kind.get("type") not in {
                "text", "email", "tel", "url", "search", "number", "textarea"
            }:
                raise ValueError("Use individual tools for credentials or non-text controls")
            if not await handle.is_visible() or not await handle.is_editable():
                raise ValueError("Field is not visible/editable")

        async def check_identity():
            if cancelled and cancelled.is_set():
                raise ValueError("Operation cancelled")
            if page.url != expected_url:
                raise ValueError("Page navigated; remaining fields were not filled")
            if not await page.evaluate("elements => elements.every(el => el && el.isConnected)", handles):
                raise ValueError("Form changed; inspect it before continuing")

        stage = "fill"
        for field, handle in zip(fields, handles):
            await check_identity()
            attempted = field["ref"]
            await handle.fill(field["value"], timeout=3000)
            if await handle.input_value() != field["value"]:
                raise ValueError("Input value differs from requested value")
            completed.append(field["ref"])
        stage = "verify"
        await check_identity()
        # Recheck earlier fields: later input handlers can alter them.
        values = await page.evaluate("elements => elements.map(el => el.value)", handles)
        if values != [field["value"] for field in fields]:
            raise ValueError("A field changed after input; inspect the form")
        return {"success": True, "completed_refs": completed, "verified": True, "submitted": False}
    except Exception as exc:
        # Do not include Playwright exception strings: they may contain values.
        return {"success": False, "completed_refs": completed, "attempted_ref": attempted,
                "verified": False, "submitted": False, "stage": stage,
                "error": str(exc) if isinstance(exc, ValueError) else "Browser operation failed; inspect the form",
                "retry_safe": False}
    finally:
        for handle in handles:
            if handle:
                try:
                    await handle.dispose()
                except Exception:
                    pass
