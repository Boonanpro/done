"""場所の地図（2026-10-25）: 成果物の地図の指紋・下書き・stamp と、部屋がどの画面に出ているかの見分け。"""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def pm(tmp_path, monkeypatch):
    monkeypatch.setenv("DAN_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    import app.agent.place_map as mod
    mod = importlib.reload(mod)
    mod._place_cache.clear()
    site = tmp_path / "artifacts" / "demo"
    (site / "_server").mkdir(parents=True)
    (site / "sub").mkdir()
    (site / "page.tsx").write_text('export default function P(){return <main><h1>見本</h1><button aria-label="保存する">保存</button></main>}')
    (site / "sub" / "page.tsx").write_text("export default function S(){return null}")
    (site / "style.module.css").write_text(".app{color:red}")
    (site / "_server" / "routes.py").write_text("router = None")
    yield mod
    monkeypatch.delenv("DAN_ARTIFACTS_DIR")
    importlib.reload(mod)


def fill(pm, slug="demo"):
    p = pm.ARTIFACTS_DIR / slug / pm.MAP_NAME
    p.write_text(p.read_text(encoding="utf-8").replace(pm.TODO, "書いた"), encoding="utf-8")


def test_draft_is_not_fresh_until_filled_and_stamped(pm):
    (pm.ARTIFACTS_DIR / "demo" / "MAP.md").write_text(pm.draft_text("demo", "見本"), encoding="utf-8")
    assert pm.map_state("demo")[0] == "DRAFT"
    fill(pm)
    assert pm.map_state("demo")[0] == "STALE"          # 指紋がまだ空
    (pm.ARTIFACTS_DIR / "demo" / "MAP.md").write_text(pm.stamp_text("demo"), encoding="utf-8")
    assert pm.map_state("demo")[0] == "FRESH"


def test_screen_change_makes_map_stale_but_server_and_map_do_not(pm):
    (pm.ARTIFACTS_DIR / "demo" / "MAP.md").write_text(pm.draft_text("demo"), encoding="utf-8")
    fill(pm)
    (pm.ARTIFACTS_DIR / "demo" / "MAP.md").write_text(pm.stamp_text("demo"), encoding="utf-8")
    (pm.ARTIFACTS_DIR / "demo" / "_server" / "routes.py").write_text("router = 1")
    (pm.ARTIFACTS_DIR / "demo" / "release.gen.json").write_text("{}")
    assert pm.map_state("demo")[0] == "FRESH"
    (pm.ARTIFACTS_DIR / "demo" / "style.module.css").write_text(".app{color:blue}")
    assert pm.map_state("demo")[0] == "STALE"


def test_missing_map(pm):
    assert pm.map_state("demo")[0] == "MISSING"


def test_code_inventory_lists_pages_server_and_handles(pm):
    text = pm.code_inventory("demo")
    assert "`/preview/demo`" in text and "`/preview/demo/sub`" in text
    assert "`_server`" in text and "「保存する」" in text and "「見本」" in text


def test_stamp_keeps_written_sections_and_reports_changed_handles(pm):
    (pm.ARTIFACTS_DIR / "demo" / "MAP.md").write_text(pm.draft_text("demo"), encoding="utf-8")
    fill(pm)
    old = (pm.ARTIFACTS_DIR / "demo" / "MAP.md").read_text(encoding="utf-8")
    (pm.ARTIFACTS_DIR / "demo" / "page.tsx").write_text('export default function P(){return <button aria-label="送る">送る</button>}')
    new = pm.stamp_text("demo")
    assert "書いた" in new and new.count(pm.AUTO_START) == 1
    gone, added = pm.inventory_changes(old, new)
    assert "ラベル: 保存する" in gone and "ラベル: 送る" in added


class FakeQuery:
    def __init__(self, rows):
        self.rows, self.filters = rows, {}

    def select(self, *_):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def order(self, *_, **__):
        return self

    def limit(self, *_):
        return self

    def execute(self):
        data = [r for r in self.rows if all(r.get(k) == v for k, v in self.filters.items())]
        return type("R", (), {"data": data})()


class FakeSb:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeQuery(self.tables.get(name, []))


SB = FakeSb({
    "projects": [
        {"id": "p-branch", "room_id": "r-branch", "title": "ダン開発室: 枝", "metadata": {"hidden": True}, "origin_room_id": "r-lead"},
        {"id": "p-lead", "room_id": "r-lead", "title": "ダン開発室", "metadata": {}, "origin_room_id": None},
        {"id": "p-chat", "room_id": "r-chat", "title": "ふつうの部屋", "metadata": {}, "origin_room_id": None},
    ],
    "chat_artifact": [
        {"room_id": "r-lead", "project_id": "p-lead", "slug": "dev-lead", "updated_at": "2"},
    ],
})


def test_identify_place(pm):
    assert pm.identify_place("r-branch", sb=SB) == {"kind": "dev-lead-room", "board_slug": "dev-lead"}
    assert pm.identify_place("r-lead", sb=SB)["kind"] == "artifact-tab"
    assert pm.identify_place("r-lead", sb=SB)["slug"] == "dev-lead"
    assert pm.identify_place("r-chat", sb=SB) == {"kind": "chat"}


def test_place_context_uses_common_and_artifact_maps(pm):
    site = pm.ARTIFACTS_DIR / "dev-lead"
    site.mkdir()
    (site / "page.tsx").write_text("x")
    (site / "MAP.md").write_text("---\nplace: artifact:dev-lead\nname: ボード\nspeak: |\n  - 付箋は札の言葉で呼ぶ\n---\n# ボード\n", encoding="utf-8")
    ctx = pm.place_context("r-branch", sb=SB)
    assert ctx.startswith("<place>") and ctx.endswith("</place>")
    assert "開発室のボードの話し合い" in ctx and "付箋は札の言葉で呼ぶ" in ctx
    assert "<place>" in pm.place_context("r-chat", sb=SB)
    assert "地図はまだ無い" not in pm.place_context("r-chat", sb=SB)


def test_place_context_survives_db_failure(pm):
    class Broken:
        def table(self, name):
            raise RuntimeError("db down")
    assert pm.place_context("r-x", sb=Broken()) == ""


def test_common_maps_parse_and_speak():
    import app.agent.place_map as mod
    for pid in ("chat", "artifact-tab", "dev-lead-room", "mobile"):
        m = mod.place_map(pid)
        assert m and m["meta"]["place"] == pid and m["meta"]["speak"].strip(), pid
        for head in ("## 中にある物", "## 行き方（みきさんから見て）", "## 道具で動かす", "## 落とし穴"):
            assert head in m["body"], (pid, head)


def test_cli_check_exit_codes(pm, tmp_path):
    env = {**__import__("os").environ, "DAN_ARTIFACTS_DIR": str(pm.ARTIFACTS_DIR)}
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts" / "place_map.py"), *a], capture_output=True, text=True, env=env)
    r = run("check", "demo")
    assert r.returncode == 2 and "[place_map] slug=demo result=MISSING" in r.stdout
    r = run("draft", "demo", "見本")
    assert r.returncode == 1 and "result=DRAFT" in r.stdout
    fill(pm)
    r = run("stamp", "demo")
    assert r.returncode == 0 and "result=FRESH" in r.stdout
