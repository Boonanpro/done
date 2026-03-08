import asyncio
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

    async def get_project_by_room_id(self, room_id: str) -> Optional[dict]:
        for project in self.projects.values():
            if project["room_id"] == room_id:
                return project
        return None

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
        run_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        for p in self.proposals[project_id]:
            if p["status"] == "pending":
                p["status"] = "superseded"
        proposal = {
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "run_id": run_id,
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
        run_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        tool_label: Optional[str] = None,
        content: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        event = {
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "run_id": run_id,
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
        run_id: Optional[str] = None,
    ) -> list[dict]:
        rows = self.execution_events.get(project_id, [])
        if run_id is not None:
            rows = [r for r in rows if r.get("run_id") == run_id]
        if since_seq is not None:
            rows = [r for r in rows if (r.get("seq") or 0) > since_seq]
        return rows[:limit]


class FakeRunService:
    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}

    async def create_run(
        self,
        project_id: str,
        room_id: str,
        claude_session_id: Optional[str] = None,
        parent_run_id: Optional[str] = None,
        state: str = "running",
        metadata: Optional[dict] = None,
    ) -> dict:
        now = datetime.now(timezone.utc)
        run = {
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "room_id": room_id,
            "claude_session_id": claude_session_id,
            "parent_run_id": parent_run_id,
            "state": state,
            "active_proposal_id": None,
            "superseded_by_run_id": None,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }
        self.runs[run["id"]] = run
        return run

    async def get_current_run(self, project_id: str) -> Optional[dict]:
        rows = [r for r in self.runs.values() if r["project_id"] == project_id]
        if not rows:
            return None
        rows.sort(key=lambda row: row["created_at"], reverse=True)
        for row in rows:
            if row.get("state") != "superseded" and not row.get("superseded_by_run_id"):
                return row
        return rows[0]

    async def update_run(self, run_id: str, **updates) -> Optional[dict]:
        run = self.runs.get(run_id)
        if not run:
            return None
        run.update(updates)
        run["updated_at"] = datetime.now(timezone.utc)
        return run

    async def attach_claude_session(self, run_id: str, claude_session_id: str) -> Optional[dict]:
        return await self.update_run(run_id, claude_session_id=claude_session_id)

    async def supersede_run(self, old_run_id: str, new_run_id: str) -> Optional[dict]:
        return await self.update_run(
            old_run_id,
            state="superseded",
            superseded_by_run_id=new_run_id,
        )


@pytest.fixture
def project_test_context(client):
    from main import app
    from app.api import project_routes

    fake_service = FakeProjectService()
    fake_run_service = FakeRunService()
    fake_service.run_service = fake_run_service

    async def fake_current_user() -> TokenData:
        return TokenData(
            user_id="test-user",
            email="test@example.com",
            exp=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    app.dependency_overrides[project_routes.get_project_service] = lambda: fake_service
    app.dependency_overrides[project_routes.get_run_service] = lambda: fake_run_service
    app.dependency_overrides[project_routes.get_current_user] = fake_current_user
    try:
        yield fake_service
    finally:
        app.dependency_overrides.pop(project_routes.get_project_service, None)
        app.dependency_overrides.pop(project_routes.get_run_service, None)
        app.dependency_overrides.pop(project_routes.get_current_user, None)


def test_proposal_approve_saves_active_plan(client, project_test_context, tmp_path, monkeypatch):
    """承認ボタンを押すと active.md に計画が保存される"""
    fake_service: FakeProjectService = project_test_context

    # active.md の保存先をtmpに変更
    plans_dir = tmp_path / "plans"
    monkeypatch.setattr(
        "app.agent.bootstrap_context.WORKSPACE_DIR",
        tmp_path,
    )

    create_project = client.post(
        "/api/v1/projects",
        json={"title": "Plan Save Test", "description": "test active plan save"},
    )
    assert create_project.status_code == 201
    project = create_project.json()
    project_id = project["id"]

    create_proposal = client.post(
        f"/api/v1/projects/{project_id}/proposals",
        json={
            "content": "## HP制作計画\n1. v0.devでコンポーネント生成\n2. デプロイ",
            "proposal_type": "plan",
            "steps": [
                {"step_number": 1, "description": "v0.devでコンポーネント生成", "status": "pending"},
                {"step_number": 2, "description": "Cloudflareにデプロイ", "status": "pending"},
            ],
        },
    )
    assert create_proposal.status_code == 201
    proposal = create_proposal.json()

    approve = client.post(
        f"/api/v1/projects/{project_id}/proposals/{proposal['id']}/action",
        json={"action": "approve"},
    )
    assert approve.status_code == 200

    # active.md が作成されたことを確認
    active_plan_path = plans_dir / "active.md"
    assert active_plan_path.exists()
    content = active_plan_path.read_text(encoding="utf-8")
    assert "Plan Save Test" in content
    assert "v0.devでコンポーネント生成" in content
    assert "Cloudflareにデプロイ" in content


def test_proposal_reject_clears_active_plan(client, project_test_context, tmp_path, monkeypatch):
    """却下すると active.md が削除される"""
    fake_service: FakeProjectService = project_test_context

    plans_dir = tmp_path / "plans"
    plans_dir.mkdir(parents=True)
    (plans_dir / "active.md").write_text("dummy plan", encoding="utf-8")
    monkeypatch.setattr(
        "app.agent.bootstrap_context.WORKSPACE_DIR",
        tmp_path,
    )

    create_project = client.post(
        "/api/v1/projects",
        json={"title": "Reject Test", "description": "test reject clears plan"},
    )
    assert create_project.status_code == 201
    project = create_project.json()
    project_id = project["id"]

    create_proposal = client.post(
        f"/api/v1/projects/{project_id}/proposals",
        json={
            "content": "## 計画\n1. 何かする",
            "proposal_type": "plan",
            "steps": [{"step_number": 1, "description": "何かする", "status": "pending"}],
        },
    )
    assert create_proposal.status_code == 201
    proposal = create_proposal.json()

    reject = client.post(
        f"/api/v1/projects/{project_id}/proposals/{proposal['id']}/action",
        json={"action": "reject"},
    )
    assert reject.status_code == 200
    assert not (plans_dir / "active.md").exists()


def test_get_current_run(client, project_test_context):
    fake_service: FakeProjectService = project_test_context
    fake_run_service: FakeRunService = fake_service.run_service

    create_project = client.post(
        "/api/v1/projects",
        json={"title": "Run Test", "description": "current run endpoint"},
    )
    assert create_project.status_code == 201
    project = create_project.json()

    run = asyncio.run(
        fake_run_service.create_run(
            project_id=project["id"],
            room_id=project["room_id"],
            state="running",
        )
    )

    response = client.get(f"/api/v1/projects/{project['id']}/current-run")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == run["id"]
    assert body["project_id"] == project["id"]
    assert body["state"] == "running"


def test_get_current_run_skips_superseded_run(client, project_test_context):
    fake_service: FakeProjectService = project_test_context
    fake_run_service: FakeRunService = fake_service.run_service

    create_project = client.post(
        "/api/v1/projects",
        json={"title": "Supersede Test", "description": "current run skips superseded"},
    )
    assert create_project.status_code == 201
    project = create_project.json()

    first_run = asyncio.run(
        fake_run_service.create_run(
            project_id=project["id"],
            room_id=project["room_id"],
            state="running",
        )
    )
    second_run = asyncio.run(
        fake_run_service.create_run(
            project_id=project["id"],
            room_id=project["room_id"],
            parent_run_id=first_run["id"],
            state="running",
        )
    )
    asyncio.run(fake_run_service.supersede_run(first_run["id"], second_run["id"]))

    response = client.get(f"/api/v1/projects/{project['id']}/current-run")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == second_run["id"]
    assert body["state"] == "running"


# ==================== create_proposal ツールのテスト ====================

@pytest.mark.asyncio
async def test_create_proposal_tool_success(monkeypatch):
    """create_proposalツールが正常に提案を作成する"""
    from app.agent.v2.tools import _execute_create_proposal

    fake_service = FakeProjectService()
    # プロジェクトを事前作成
    project = await fake_service.create_project(
        user_id="test-user",
        title="Tool Test",
        description="test create_proposal tool",
    )
    room_id = project["room_id"]

    # ProjectServiceをモック
    monkeypatch.setattr(
        "app.agent.v2.tools._get_project_service",
        lambda: fake_service,
    )

    result = await _execute_create_proposal(
        params={
            "title": "HP制作計画",
            "steps": [
                "v0.devでコンポーネント生成",
                "Claude Codeでコード調整",
                "Cloudflareにデプロイ",
            ],
        },
        user_id="test-user",
        session_id=room_id,
    )

    assert result["success"] is True
    assert "proposal_id" in result

    # DBに保存されたか確認
    proposals = await fake_service.get_proposals(project["id"])
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["status"] == "pending"
    assert len(proposal["steps"]) == 3
    assert proposal["steps"][0]["description"] == "v0.devでコンポーネント生成"
    assert proposal["steps"][1]["step_number"] == 2
    assert proposal["metadata"]["source"] == "create_proposal_tool"

    # プロジェクトステータスが proposed になったか
    updated_project = await fake_service.get_project(project["id"], "test-user")
    assert updated_project["status"] == "proposed"


@pytest.mark.asyncio
async def test_create_proposal_tool_no_session():
    """セッションIDなしでエラーを返す"""
    from app.agent.v2.tools import _execute_create_proposal

    result = await _execute_create_proposal(
        params={"title": "テスト", "steps": ["ステップ1"]},
        user_id="test-user",
        session_id=None,
    )
    assert result["success"] is False
    assert "セッションID" in result["error"]


@pytest.mark.asyncio
async def test_create_proposal_tool_no_project(monkeypatch):
    """プロジェクトが見つからない場合エラーを返す"""
    from app.agent.v2.tools import _execute_create_proposal

    fake_service = FakeProjectService()
    monkeypatch.setattr(
        "app.agent.v2.tools._get_project_service",
        lambda: fake_service,
    )

    result = await _execute_create_proposal(
        params={"title": "テスト", "steps": ["ステップ1"]},
        user_id="test-user",
        session_id="nonexistent-room",
    )
    assert result["success"] is False
    assert "プロジェクトが見つかりません" in result["error"]


@pytest.mark.asyncio
async def test_create_proposal_tool_empty_title():
    """タイトルなしでエラーを返す"""
    from app.agent.v2.tools import _execute_create_proposal

    result = await _execute_create_proposal(
        params={"title": "", "steps": ["ステップ1"]},
        user_id="test-user",
        session_id="some-room",
    )
    assert result["success"] is False
    assert "タイトル" in result["error"]


@pytest.mark.asyncio
async def test_create_proposal_tool_empty_steps():
    """ステップなしでエラーを返す"""
    from app.agent.v2.tools import _execute_create_proposal

    result = await _execute_create_proposal(
        params={"title": "テスト", "steps": []},
        user_id="test-user",
        session_id="some-room",
    )
    assert result["success"] is False
    assert "ステップ" in result["error"]


@pytest.mark.asyncio
async def test_create_proposal_tool_supersedes_pending(monkeypatch):
    """新しい提案が既存のpending提案をsupersededにする"""
    from app.agent.v2.tools import _execute_create_proposal

    fake_service = FakeProjectService()
    project = await fake_service.create_project(
        user_id="test-user",
        title="Supersede Test",
    )
    room_id = project["room_id"]

    monkeypatch.setattr(
        "app.agent.v2.tools._get_project_service",
        lambda: fake_service,
    )

    # 1つ目の提案
    await _execute_create_proposal(
        params={"title": "計画v1", "steps": ["ステップA"]},
        user_id="test-user",
        session_id=room_id,
    )

    # 2つ目の提案
    result = await _execute_create_proposal(
        params={"title": "計画v2", "steps": ["ステップB"]},
        user_id="test-user",
        session_id=room_id,
    )
    assert result["success"] is True

    proposals = await fake_service.get_proposals(project["id"])
    statuses = [p["status"] for p in proposals]
    assert statuses.count("pending") == 1
    assert statuses.count("superseded") == 1
