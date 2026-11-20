"""子ブロック一覧で、画像の中身を外して返せること（開発室のボードを外の回線でも軽く開くため。11-08）"""
from datetime import datetime, timedelta

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
        "created_at": "2026-11-08T00:00:00+00:00", "updated_at": "2026-11-08T00:00:00+00:00",
    }


class _Svc:
    def get_block(self, user_id, block_id):
        return {"id": block_id}

    def list_children(self, user_id, parent_id):
        return [_row(1, {"image": {"hash": "h1", "data": "data:image/png;base64,AAAA"}}), _row(2, {"thread": {"room_id": "r"}})]

    def list_children_light(self, user_id, parent_id):
        return [_row(1, {"image": {"hash": "h1"}}), _row(2, {"thread": {"room_id": "r"}})]


def _client(monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_current_user] = lambda: TokenData(user_id=USER, email="t@example.com", exp=datetime.now() + timedelta(hours=1))
    monkeypatch.setattr(routes, "_svc", lambda: _Svc())
    return TestClient(app)


def test_children_keep_image_data_by_default(monkeypatch):
    rows = _client(monkeypatch).get(f"/dan-notion/blocks/{PARENT}/children").json()
    assert rows[0]["properties"]["image"] == {"hash": "h1", "data": "data:image/png;base64,AAAA"}


def test_children_omit_image_data(monkeypatch):
    rows = _client(monkeypatch).get(f"/dan-notion/blocks/{PARENT}/children?omit_image_data=true").json()
    assert rows[0]["properties"]["image"] == {"hash": "h1"}
    assert rows[1]["properties"] == {"thread": {"room_id": "r"}}


class _Query:
    """A stand-in for the Supabase table query: keeps the filters and answers like the database would."""
    def __init__(self, rows):
        self.rows, self.cols, self.image = rows, "*", None

    def select(self, cols):
        self.cols = cols
        return self

    def eq(self, *_):
        return self

    def order(self, *_):
        return self

    def is_(self, col, _):
        if col == "properties->image": self.image = False
        return self

    @property
    def not_(self):
        outer = self

        class _Not:
            def is_(self, col, _):
                if col == "properties->image": outer.image = True
                return outer
        return _Not()

    def execute(self):
        rows = sorted(self.rows, key=lambda r: r["order_key"])
        if self.image is not None:
            rows = [r for r in rows if ("image" in r["properties"]) == self.image]
        if self.cols == "*":
            data = [dict(r) for r in rows]
        else:
            data = []
            for r in rows:
                d = {k: v for k, v in r.items() if k != "properties"}
                d["image_hash"] = (r["properties"].get("image") or {}).get("hash")
                data.append(d)
        return type("R", (), {"data": data})()


def test_light_children_read_only_the_hash_and_keep_the_order():
    from app.services.dan_notion_service import DanNotionService
    rows = [_row(3, {"thread": {"room_id": "r"}}), _row(1, {"image": {"hash": "h1", "data": "data:image/png;base64,AAAA"}}),
            _row(2, {"goal": {"text": "g"}})]
    svc = DanNotionService.__new__(DanNotionService)
    svc.sb = type("SB", (), {"table": lambda self, name: _Query(rows)})()
    out = svc.list_children_light(USER, PARENT)
    assert [r["order_key"] for r in out] == ["1", "2", "3"]
    assert out[0]["properties"] == {"image": {"hash": "h1"}}
    assert out[1]["properties"] == {"goal": {"text": "g"}}
    assert out[2]["properties"] == {"thread": {"room_id": "r"}}
