"""子ブロック一覧で、画像の中身を外して返せること（開発室のボードを外の回線でも軽く開くため。11-08）"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import dan_notion_routes as routes
from app.services.auth_service import TokenData

USER = "00000000-0000-0000-0000-000000000001"
PARENT = "00000000-0000-0000-0000-0000000000aa"


def _row(n: int, properties: dict) -> dict:
    return {
        "id": f"00000000-0000-0000-0000-00000000000{n}", "user_id": USER, "parent_id": PARENT, "type": "paragraph",
        "order_key": str(n), "properties": properties, "content": None, "is_starred": False, "tags": [],
        "created_by": "dan", "source": "manual", "version": 1,
    }


class _Svc:
    def get_block(self, user_id, block_id):
        return {"id": block_id}

    def list_children(self, user_id, parent_id):
        return [_row(1, {"image": {"hash": "h1", "data": "data:image/png;base64,AAAA"}}), _row(2, {"thread": {"room_id": "r"}})]


def _client(monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_current_user] = lambda: TokenData(user_id=USER, email="t@example.com")
    monkeypatch.setattr(routes, "_svc", lambda: _Svc())
    return TestClient(app)


def test_children_keep_image_data_by_default(monkeypatch):
    rows = _client(monkeypatch).get(f"/dan-notion/blocks/{PARENT}/children").json()
    assert rows[0]["properties"]["image"] == {"hash": "h1", "data": "data:image/png;base64,AAAA"}


def test_children_omit_image_data(monkeypatch):
    rows = _client(monkeypatch).get(f"/dan-notion/blocks/{PARENT}/children?omit_image_data=true").json()
    assert rows[0]["properties"]["image"] == {"hash": "h1"}
    assert rows[1]["properties"] == {"thread": {"room_id": "r"}}
