"""制作の部屋（エディターの中の「ダンと制作」）: 作品の部屋はいつもその作品を本体の部屋で直し、本体の部屋には一覧が出る。"""
import pytest

from app.services import editor_rooms as er
from app.services import video_learning


@pytest.fixture(autouse=True)
def _private_learning_dir(monkeypatch, tmp_path):
    """制作の部屋の控え（video_learning.remember_editor_room）を本物の場所に書かない。"""
    monkeypatch.setattr(video_learning, "ROOT", tmp_path / "video-learning")


def _info(monkeypatch, table):
    monkeypatch.setattr(er, "room_info", lambda rid, sb=None: table.get(rid))


def test_content_room_always_targets_its_content_in_the_asset_room(monkeypatch):
    from app.api.chat_routes import _auto_timeline_refs
    _info(monkeypatch, {"c1": {"asset_room_id": "A", "content_id": "K", "kind": "content", "title": "制作: v1",
                              "parent_title": "中村さん", "parent_project_id": "p"}})
    assert _auto_timeline_refs("c1", None) == [{"content_id": "K", "room_id": "A"}]
    # 明示の言及が勝つ
    assert _auto_timeline_refs("c1", [{"content_id": "X"}]) == [{"content_id": "X"}]


def test_library_room_reads_the_asset_rooms_editor_state(monkeypatch, tmp_path):
    from app.api.chat_routes import _auto_timeline_refs
    from app.services import timeline_live
    _info(monkeypatch, {"L": {"asset_room_id": "A", "content_id": None, "kind": "library", "title": "",
                             "parent_title": "", "parent_project_id": ""}})
    seen = []
    monkeypatch.setattr(timeline_live, "editor_state", lambda rid, max_age_s=0: seen.append(rid) or {"content_id": "K2"})
    assert _auto_timeline_refs("L", None) == [{"content_id": "K2", "room_id": "A"}]
    assert seen == ["A"]


def test_asset_room_falls_back_to_the_room_itself(monkeypatch):
    _info(monkeypatch, {"c1": {"asset_room_id": "A"}})
    assert er.asset_room("c1") == "A"
    assert er.asset_room("plain") == "plain"


def test_context_lines_link_both_ways(monkeypatch):
    _info(monkeypatch, {"c1": {"asset_room_id": "A", "content_id": "K", "kind": "content", "title": "制作: v1",
                              "parent_title": "中村さん", "parent_project_id": "p"}})
    kids = [{"room_id": "c1", "title": "制作: v1", "content_id": "K", "last_message_at": "2026-11-12T01:00:00", "preview": "字幕を直しました"},
            {"room_id": "L", "title": "制作ライブラリ: 中村さん", "content_id": None, "last_message_at": "", "preview": ""}]
    monkeypatch.setattr(er, "children", lambda rid, sb=None: kids if rid == "A" else [])
    child = "\n".join(er.context_lines("c1"))
    assert "room_id=A" in child and "content_id=K" in child and "制作ライブラリ: 中村さん" in child
    assert "制作: v1 (room_id=c1)" not in child   # 自分は兄弟の一覧に入れない
    parent = "\n".join(er.context_lines("A"))
    assert "制作: v1 (room_id=c1)" in parent and "字幕を直しました" in parent


def test_ensure_room_makes_one_room_when_asked_twice_at_once(monkeypatch):
    # 窓をすぐ開き直すと「ダンと制作」の部屋の作成が同時に2回届き、部屋が2つできていた（2026-11-12）。
    import asyncio
    from app.services import editor_rooms as er
    from app.services import project_service as ps

    rows: list[dict] = []

    class Q:
        def __init__(self, table):
            self.table = table
            self.filters = {}
            self.n = None

        def select(self, *_a):
            return self

        def eq(self, k, v):
            self.filters[k] = v
            return self

        def limit(self, n):
            self.n = n
            return self

        def execute(self):
            if self.table != "projects":
                return type("R", (), {"data": []})()
            data = [r for r in rows if all(r.get(k) == v for k, v in self.filters.items())]
            return type("R", (), {"data": data[: self.n] if self.n else data})()

    class SB:
        def table(self, name):
            return Q(name)

    made = []

    class FakeProjects:
        async def create_project(self, user_id, title, description="", origin_room_id=None, metadata=None):
            await asyncio.sleep(0.05)   # 本物も作るのに時間がかかる。その間に2回目が来る
            row = {"id": f"p{len(made)}", "room_id": f"r{len(made)}", "title": title, "metadata": metadata,
                   "origin_room_id": origin_room_id, "user_id": user_id, "created_at": f"2026-11-12T00:00:0{len(made)}"}
            made.append(row)
            rows.append(row)
            return row

    monkeypatch.setattr(ps, "ProjectService", FakeProjects)

    async def both():
        sb = SB()
        return await asyncio.gather(er.ensure_room("u", "asset", None, sb=sb), er.ensure_room("u", "asset", None, sb=sb))

    a, b = asyncio.run(both())
    assert len(made) == 1
    assert a["room_id"] == b["room_id"]
