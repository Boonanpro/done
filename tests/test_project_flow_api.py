import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest

from app.services.auth_service import TokenData


class FakeProjectService:
    def __init__(self) -> None:
        self.projects: dict[str, dict] = {}
        self.proposals: dict[str, list[dict]] = {}
        self.execution_events: dict[str, list[dict]] = {}
        self.seq = 1

    async def create_project(
        self,
        user_id: str,
        title: str,
        description: Optional[str] = None,
        origin_room_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        project_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        project = {
            "id": project_id,
            "user_id": user_id,
            "title": title,
            "description": description,
            "status": "planning",
            "room_id": f"room-{project_id}",
            "origin_room_id": origin_room_id,
            "summary": None,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }
        self.projects[project_id] = project
        self.proposals[project_id] = []
        return project

    async def get_project(self, project_id: str, user_id: str) -> Optional[dict]:
        project = self.projects.get(project_id)
        if not project or project["user_id"] != user_id:
            return None
        return project

    async def list_projects(self, user_id: str, status: Optional[str] = None) -> list[dict]:
        rows = [p for p in self.projects.values() if p["user_id"] == user_id]
        if status:
            rows = [p for p in rows if p["status"] == status]
        return rows

    async def update_project(self, project_id: str, user_id: str, **updates) -> Optional[dict]:
        project = self.projects.get(project_id)
        if not project or project["user_id"] != user_id:
            return None
        project.update(updates)
        project["updated_at"] = datetime.now(timezone.utc)
        return project

    async def delete_project(self, project_id: str, user_id: str) -> bool:
        project = self.projects.get(project_id)
        if not project or project["user_id"] != user_id:
            return False
        del self.projects[project_id]
        self.proposals.pop(project_id, None)
        self.execution_events.pop(project_id, None)
        return True

    async def create_proposal(
        self,
        project_id: str,
        content: str,
        proposal_type: str = "plan",
        steps: Optional[list] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        for p in self.proposals[project_id]:
            if p["status"] == "pending":
                p["status"] = "superseded"
        proposal = {
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "content": content,
            "proposal_type": proposal_type,
            "status": "pending",
            "steps": steps or [],
            "metadata": metadata or {},
            "approved_at": None,
            "created_at": datetime.now(timezone.utc),
        }
        self.proposals[project_id].append(proposal)
        self.projects[project_id]["status"] = "proposed"
        self.projects[project_id]["updated_at"] = datetime.now(timezone.utc)
        return proposal

    async def get_proposals(self, project_id: str) -> list[dict]:
        return list(reversed(self.proposals.get(project_id, [])))

    async def approve_proposal(self, proposal_id: str, project_id: str) -> Optional[dict]:
        for proposal in self.proposals.get(project_id, []):
            if proposal["id"] == proposal_id and proposal["status"] == "pending":
                proposal["status"] = "approved"
                proposal["approved_at"] = datetime.now(timezone.utc)
                self.projects[project_id]["status"] = "approved"
                self.projects[project_id]["updated_at"] = datetime.now(timezone.utc)
                return proposal
        return None

    async def reject_proposal(self, proposal_id: str, project_id: str) -> Optional[dict]:
        for proposal in self.proposals.get(project_id, []):
            if proposal["id"] == proposal_id and proposal["status"] == "pending":
                proposal["status"] = "rejected"
                self.projects[project_id]["status"] = "planning"
                self.projects[project_id]["updated_at"] = datetime.now(timezone.utc)
                return proposal
        return None

    async def save_execution_event(
        self,
        project_id: Optional[str],
        room_id: str,
        event_type: str,
        tool_name: Optional[str] = None,
        tool_label: Optional[str] = None,
        content: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        event = {
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "room_id": room_id,
            "event_type": event_type,
            "tool_name": tool_name,
            "tool_label": tool_label,
            "content": content,
            "metadata": metadata or {},
            "seq": self.seq,
            "created_at": datetime.now(timezone.utc),
        }
        self.seq += 1
        if project_id:
            self.execution_events.setdefault(project_id, []).append(event)
        return event

    async def get_execution_events(
        self,
        project_id: str,
        limit: int = 100,
        after: Optional[str] = None,
        since_seq: Optional[int] = None,
    ) -> list[dict]:
        rows = self.execution_events.get(project_id, [])
        if since_seq is not None:
            rows = [r for r in rows if (r.get("seq") or 0) > since_seq]
        return rows[:limit]


@pytest.fixture
def project_test_context(client):
    from main import app
    from app.api import project_routes

    fake_service = FakeProjectService()

    async def fake_current_user() -> TokenData:
        return TokenData(
            user_id="test-user",
            email="test@example.com",
            exp=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    app.dependency_overrides[project_routes.get_project_service] = lambda: fake_service
    app.dependency_overrides[project_routes.get_current_user] = fake_current_user
    try:
        yield fake_service
    finally:
        app.dependency_overrides.pop(project_routes.get_project_service, None)
        app.dependency_overrides.pop(project_routes.get_current_user, None)


def _wait_for_project_status(
    client: Any,
    project_id: str,
    expected_status: str,
    timeout_sec: float = 2.0,
) -> dict:
    deadline = time.time() + timeout_sec
    last = {}
    while time.time() < deadline:
        response = client.get(f"/api/v1/projects/{project_id}")
        assert response.status_code == 200
        last = response.json()
        if last.get("status") == expected_status:
            return last
        time.sleep(0.05)
    raise AssertionError(
        f"project status did not become '{expected_status}', last={last.get('status')}"
    )


def test_project_flow_awaiting_then_cancel(client, project_test_context, monkeypatch):
    fake_service: FakeProjectService = project_test_context

    async def fake_start_project_execution(project: dict, proposal: dict, user_id: str):
        await fake_service.update_project(
            project["id"],
            user_id,
            status="awaiting_confirmation",
            metadata={
                "pending_step": 1,
                "proposal_id": proposal["id"],
                "previous_results": [],
            },
        )

    monkeypatch.setattr(
        "app.api.project_routes._start_project_execution",
        fake_start_project_execution,
    )

    create_project = client.post(
        "/api/v1/projects",
        json={"title": "Flow Test A", "description": "project flow cancel path"},
    )
    assert create_project.status_code == 201
    project = create_project.json()
    project_id = project["id"]
    assert project["status"] == "planning"

    create_proposal = client.post(
        f"/api/v1/projects/{project_id}/proposals",
        json={
            "content": "## 実行計画\n1. 購入を確定する",
            "proposal_type": "plan",
            "steps": [
                {"step_number": 1, "description": "購入を確定する", "status": "pending"}
            ],
        },
    )
    assert create_proposal.status_code == 201
    proposal = create_proposal.json()

    after_proposal = client.get(f"/api/v1/projects/{project_id}")
    assert after_proposal.status_code == 200
    assert after_proposal.json()["status"] == "proposed"

    approve = client.post(
        f"/api/v1/projects/{project_id}/proposals/{proposal['id']}/action",
        json={"action": "approve"},
    )
    assert approve.status_code == 200

    waiting_project = _wait_for_project_status(client, project_id, "awaiting_confirmation")
    assert waiting_project.get("metadata", {}).get("pending_step") == 1

    cancel = client.post(
        f"/api/v1/projects/{project_id}/resume",
        json={"action": "cancel"},
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "paused"


def test_project_flow_awaiting_then_confirm_to_completed(
    client, project_test_context, monkeypatch
):
    fake_service: FakeProjectService = project_test_context

    async def fake_start_project_execution(project: dict, proposal: dict, user_id: str):
        await fake_service.update_project(
            project["id"],
            user_id,
            status="awaiting_confirmation",
            metadata={
                "pending_step": 1,
                "proposal_id": proposal["id"],
                "previous_results": [],
            },
        )

    async def fake_run_stepwise_execution(*args, **kwargs):
        project_id = kwargs.get("project_id") or args[0]
        user_id = kwargs.get("user_id")
        if user_id is None and len(args) > 2:
            user_id = args[2]
        await fake_service.update_project(project_id, user_id, status="completed")

    monkeypatch.setattr(
        "app.api.project_routes._start_project_execution",
        fake_start_project_execution,
    )
    monkeypatch.setattr(
        "app.services.project_execution.run_stepwise_execution",
        fake_run_stepwise_execution,
    )

    create_project = client.post(
        "/api/v1/projects",
        json={"title": "Flow Test B", "description": "project flow confirm path"},
    )
    assert create_project.status_code == 201
    project_id = create_project.json()["id"]

    create_proposal = client.post(
        f"/api/v1/projects/{project_id}/proposals",
        json={
            "content": "## 実行計画\n1. 実装する",
            "proposal_type": "plan",
            "steps": [{"step_number": 1, "description": "実装する", "status": "pending"}],
        },
    )
    assert create_proposal.status_code == 201
    proposal = create_proposal.json()

    approve = client.post(
        f"/api/v1/projects/{project_id}/proposals/{proposal['id']}/action",
        json={"action": "approve"},
    )
    assert approve.status_code == 200

    _wait_for_project_status(client, project_id, "awaiting_confirmation")

    confirm = client.post(
        f"/api/v1/projects/{project_id}/resume",
        json={"action": "confirm"},
    )
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "in_progress"

    completed_project = _wait_for_project_status(client, project_id, "completed")
    assert completed_project["status"] == "completed"

