import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen
from urllib.parse import urlparse

import pytest


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_frontend_available(base_url: str) -> None:
    try:
        with urlopen(f"{base_url}/chat", timeout=2):
            return
    except URLError:
        pytest.skip(f"frontend server is not reachable at {base_url}")


@dataclass
class MockProjectBackend:
    project_id: str = "project-recovery"
    room_id: str = "room-recovery"
    project_title: str = "Recovery Project"
    active: bool = False
    messages: list[dict[str, Any]] = field(default_factory=list)
    execution_events: list[dict[str, Any]] = field(default_factory=list)
    last_user_message: dict[str, Any] | None = None

    @property
    def project(self) -> dict[str, Any]:
        now = iso_now()
        return {
            "id": self.project_id,
            "user_id": "user-1",
            "title": self.project_title,
            "description": None,
            "status": "in_progress",
            "room_id": self.room_id,
            "origin_room_id": None,
            "summary": None,
            "metadata": None,
            "created_at": now,
            "updated_at": now,
        }

    def stream_body(self, user_content: str, *, include_done: bool = True) -> str:
        now = iso_now()
        self.last_user_message = {
            "id": "msg-user-1",
            "room_id": self.room_id,
            "sender_id": "user-1",
            "sender_name": "E2E User",
            "sender_type": "human",
            "content": user_content,
            "created_at": now,
        }

        events: list[dict[str, Any]] = [
            {
                "type": "user_message",
                "message": self.last_user_message,
                "session_id": self.room_id,
            },
            {
                "type": "process",
                "step": {
                    "id": "step-1",
                    "label": "Inspecting project state",
                    "status": "running",
                },
                "session_id": self.room_id,
            },
        ]
        if include_done:
            events.append({
                "type": "done",
                "session_id": self.room_id,
            })
        return "".join(f"data: {json.dumps(event)}\n\n" for event in events)

    def finish_recovery(self, ai_text: str = "Recovered AI response") -> None:
        if self.last_user_message is None:
            self.last_user_message = {
                "id": "msg-user-1",
                "room_id": self.room_id,
                "sender_id": "user-1",
                "sender_name": "E2E User",
                "sender_type": "human",
                "content": "hello",
                "created_at": iso_now(),
            }

        self.messages = [
            {
                "id": "msg-ai-1",
                "room_id": self.room_id,
                "sender_id": "dan",
                "sender_name": "Dan",
                "sender_type": "ai",
                "content": ai_text,
                "created_at": iso_now(),
            },
            self.last_user_message,
        ]
        self.execution_events = [
            {
                "id": "evt-1",
                "project_id": self.project_id,
                "room_id": self.room_id,
                "event_type": "tool_use",
                "tool_name": "project.lookup",
                "tool_label": "Project lookup",
                "content": None,
                "metadata": {"member": "researcher"},
                "seq": 1,
                "created_at": iso_now(),
            },
            {
                "id": "evt-2",
                "project_id": self.project_id,
                "room_id": self.room_id,
                "event_type": "done",
                "tool_name": None,
                "tool_label": None,
                "content": None,
                "metadata": None,
                "seq": 2,
                "created_at": iso_now(),
            },
        ]
        self.active = False


def install_routes(page, state: MockProjectBackend, *, include_done: bool = True) -> None:
    def handler(route) -> None:
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path
        method = request.method

        if path == "/api/v1/projects" and method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"projects": [state.project]}),
            )
            return

        if path == f"/api/v1/projects/{state.project_id}" and method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(state.project),
            )
            return

        if path == f"/api/v1/projects/{state.project_id}/proposals" and method == "GET":
            route.fulfill(status=200, content_type="application/json", body="[]")
            return

        if path == f"/api/v1/projects/{state.project_id}/execution-events" and method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(state.execution_events),
            )
            return

        if path == f"/api/v1/chat/rooms/{state.room_id}/messages" and method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"messages": state.messages}),
            )
            return

        if path == f"/api/v1/chat/dan/sessions/{state.room_id}/active" and method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "active": state.active,
                        "session_id": state.room_id,
                        "started_at": 1700000000 if state.active else None,
                    }
                ),
            )
            return

        if path == "/api/v1/chat/dan/messages/stream" and method == "POST":
            payload = json.loads(request.post_data or "{}")
            body = state.stream_body(
                payload.get("content", "hello"),
                include_done=include_done,
            )
            route.fulfill(
                status=200,
                headers={"Content-Type": "text/event-stream"},
                body=body,
            )
            return

        if path == "/api/v1/chat/dan/cancel" and method == "POST":
            state.active = False
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "session_id": state.room_id}),
            )
            return

        route.fulfill(status=404, content_type="application/json", body="{}")

    page.route("**/api/v1/**", handler)


CANCEL_BUTTON = "button[title='キャンセル']"
TEXTAREA = "textarea[placeholder='メッセージを入力...']"
WAIT_TIMEOUT = 5000


def bootstrap_chat_page(
    page, state: MockProjectBackend, base_url: str, *, mobile: bool = False, include_done: bool = True
) -> None:
    ensure_frontend_available(base_url)

    if mobile:
        page.set_viewport_size({"width": 390, "height": 844})

    page.add_init_script(
        """
        window.localStorage.setItem('done-token', 'e2e-token');
        """
    )
    install_routes(page, state, include_done=include_done)
    page.goto(f"{base_url}/chat", wait_until="domcontentloaded")
    page.wait_for_selector(f"text={state.project_title}", timeout=WAIT_TIMEOUT)
    page.locator(f"text={state.project_title}").first.click()
    page.wait_for_selector(TEXTAREA, timeout=WAIT_TIMEOUT)
    page.evaluate(
        """
        () => {
          if (window.__e2eLifecycleInstalled) return;
          window.__e2eLifecycleInstalled = true;
          let visibility = 'visible';
          Object.defineProperty(document, 'visibilityState', {
            configurable: true,
            get: () => visibility,
          });
          window.__setVisibility = (next) => {
            visibility = next;
            document.dispatchEvent(new Event('visibilitychange'));
          };
          window.__dispatchWindowEvent = (name) => window.dispatchEvent(new Event(name));
          window.__dispatchDocumentEvent = (name) => document.dispatchEvent(new Event(name));
        }
        """
    )


def send_message(page, text: str) -> None:
    textarea = page.locator(TEXTAREA)
    textarea.fill(text)
    textarea.locator("xpath=following-sibling::button").click()


@pytest.mark.e2e
def test_recovery_after_visibility_restore(browser_page):
    """タブ非表示→復帰で正しい状態になることを確認"""
    base_url = os.getenv("E2E_FRONTEND_BASE_URL", "http://127.0.0.1:3000")
    state = MockProjectBackend()
    bootstrap_chat_page(browser_page, state, base_url)

    state.active = True
    send_message(browser_page, "recover after visibility")
    browser_page.wait_for_selector(CANCEL_BUTTON, timeout=WAIT_TIMEOUT)

    browser_page.evaluate("window.__setVisibility('hidden')")
    state.finish_recovery("Recovered after visibility restore")
    browser_page.evaluate("window.__setVisibility('visible')")

    browser_page.wait_for_selector("text=Recovered after visibility restore", timeout=WAIT_TIMEOUT)
    assert browser_page.locator(CANCEL_BUTTON).count() == 0


@pytest.mark.e2e
def test_recovery_fetches_message_after_sse_interrupt(browser_page):
    """SSE切断→online復帰でメッセージを取得することを確認"""
    base_url = os.getenv("E2E_FRONTEND_BASE_URL", "http://127.0.0.1:3000")
    state = MockProjectBackend()
    bootstrap_chat_page(browser_page, state, base_url)

    state.active = True
    send_message(browser_page, "interrupt before ai")
    browser_page.wait_for_selector(CANCEL_BUTTON, timeout=WAIT_TIMEOUT)

    state.finish_recovery("Recovered after interrupted SSE")
    browser_page.evaluate("window.__dispatchWindowEvent('online')")

    browser_page.wait_for_selector("text=Recovered after interrupted SSE", timeout=WAIT_TIMEOUT)
    assert browser_page.locator(CANCEL_BUTTON).count() == 0


@pytest.mark.e2e
def test_stream_end_without_done_stops_spinner(browser_page):
    """doneイベント未着でストリームが終了してもスピナーが止まることを確認"""
    base_url = os.getenv("E2E_FRONTEND_BASE_URL", "http://127.0.0.1:3000")
    state = MockProjectBackend()
    bootstrap_chat_page(browser_page, state, base_url, include_done=False)

    send_message(browser_page, "missing done")
    # onInterrupted が発火し、recovery が active=false を検出してスピナー停止
    browser_page.wait_for_selector(TEXTAREA, timeout=WAIT_TIMEOUT)
    assert browser_page.locator(CANCEL_BUTTON).count() == 0


@pytest.mark.e2e
def test_mobile_app_switch_recovers_from_db(browser_page):
    """スマホでアプリ切替→復帰で正しい状態になることを確認"""
    base_url = os.getenv("E2E_FRONTEND_BASE_URL", "http://127.0.0.1:3000")
    state = MockProjectBackend()
    bootstrap_chat_page(browser_page, state, base_url, mobile=True)

    state.active = True
    send_message(browser_page, "mobile recovery")
    browser_page.wait_for_selector(CANCEL_BUTTON, timeout=WAIT_TIMEOUT)

    browser_page.evaluate("window.__dispatchWindowEvent('pagehide')")
    state.finish_recovery("Recovered after mobile app switch")
    browser_page.evaluate("window.__dispatchWindowEvent('pageshow')")
    browser_page.evaluate("window.__dispatchDocumentEvent('resume')")

    browser_page.wait_for_selector("text=Recovered after mobile app switch", timeout=WAIT_TIMEOUT)
    assert browser_page.locator(CANCEL_BUTTON).count() == 0
