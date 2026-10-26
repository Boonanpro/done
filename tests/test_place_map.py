"""場所の地図（2026-10-25）: 地図の指紋・下書き・stamp、共通の場所の見張るファイル、部屋がどの画面に出ているかの見分け、
会話の長い部屋の前置き。"""
import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def pm(tmp_path, monkeypatch):
    tree = tmp_path / "tree"
    places = tree / "docs" / "places"
    places.mkdir(parents=True)
    monkeypatch.setenv("DAN_ARTIFACTS_DIR", str(tree / "frontend" / "src" / "app" / "artifacts"))
    monkeypatch.setenv("DAN_PLACES_DIR", str(places))
    monkeypatch.setenv("DAN_PLACE_RUNTIME_DIR", str(tmp_path / "rt"))
    import app.agent.place_map as mod
    mod = importlib.reload(mod)
    mod._place_cache.clear()
    site = mod.ARTIFACTS_DIR / "demo"
    (site / "_server").mkdir(parents=True)
    (site / "sub").mkdir()
    (site / "page.tsx").write_text('export default function P(){return <main><h1>見本</h1><button aria-label="保存する">保存</button></main>}')
    (site / "sub" / "page.tsx").write_text("export default function S(){return null}")
    (site / "style.module.css").write_text(".app{color:red}")
    (site / "_server" / "routes.py").write_text("router = None")
    (tree / "frontend/src/components").mkdir(parents=True)
    (tree / "frontend/src/components/panel.tsx").write_text("export const A = 1")
    for pid in ("chat", "artifact-tab", "dev-lead-room", "mobile"):
        (places / f"{pid}.md").write_text(
            f"---\nplace: {pid}\nname: {pid} の名前\nspeak: |\n  - {pid} の話し方\n"
            + ("watches:\n  - frontend/src/components/*.tsx\n" if pid == "chat" else "") + f"---\n# {pid}\n", encoding="utf-8")
    yield mod
    for k in ("DAN_ARTIFACTS_DIR", "DAN_PLACES_DIR", "DAN_PLACE_RUNTIME_DIR"):
        monkeypatch.delenv(k)
    importlib.reload(mod)


def fill(pm, pid="artifact:demo"):
    p = pm.map_path(pid)
    p.write_text(p.read_text(encoding="utf-8").replace(pm.TODO, "書いた"), encoding="utf-8")


def stamp(pm, pid="artifact:demo", unchanged=""):
    pm.map_path(pid).write_text(pm.stamp_text(pid, unchanged), encoding="utf-8")


def draft(pm):
    pm.map_path("artifact:demo").write_text(pm.draft_text("demo", "見本"), encoding="utf-8")


def test_draft_is_not_fresh_until_filled_and_stamped(pm):
    draft(pm)
    assert pm.map_state("artifact:demo")[0] == "DRAFT"
    fill(pm)
    assert pm.map_state("artifact:demo")[0] == "STALE"          # 指紋がまだ無い
    stamp(pm)
    assert pm.map_state("artifact:demo")[0] == "FRESH"


def test_screen_change_makes_map_stale_but_server_and_map_do_not(pm):
    draft(pm), fill(pm), stamp(pm)
    (pm.ARTIFACTS_DIR / "demo" / "_server" / "routes.py").write_text("router = 1")
    (pm.ARTIFACTS_DIR / "demo" / "release.gen.json").write_text("{}")
    assert pm.map_state("artifact:demo")[0] == "FRESH"
    (pm.ARTIFACTS_DIR / "demo" / "style.module.css").write_text(".app{color:blue}")
    state, why = pm.map_state("artifact:demo")
    assert state == "STALE" and "style.module.css" in why


def test_stamp_refuses_when_only_the_screen_changed(pm):
    """10-25 確かめ役: ボタンを「保存」から「削除」に変えても、説明を直さず stamp するだけで FRESH になった。"""
    draft(pm), fill(pm), stamp(pm)
    page = pm.ARTIFACTS_DIR / "demo" / "page.tsx"
    page.write_text(page.read_text().replace("保存", "削除"))
    with pytest.raises(pm.StampRefused) as e:
        stamp(pm)
    assert "page.tsx" in str(e.value)
    assert pm.map_state("artifact:demo")[0] == "STALE"
    p = pm.map_path("artifact:demo")
    p.write_text(p.read_text().replace("# 見本", "# 見本（削除ボタン）"), encoding="utf-8")
    stamp(pm)
    assert pm.map_state("artifact:demo")[0] == "FRESH"


def test_unchanged_reason_lets_a_look_fix_through_and_is_recorded(pm):
    draft(pm), fill(pm), stamp(pm)
    (pm.ARTIFACTS_DIR / "demo" / "style.module.css").write_text(".app{color:blue}")
    stamp(pm, unchanged="色を直しただけ")
    text = pm.map_path("artifact:demo").read_text()
    assert pm.map_state("artifact:demo")[0] == "FRESH" and "説明は変えない: 色を直しただけ" in text


def test_common_place_watches_files(pm):
    stamp(pm, "chat")
    assert pm.map_state("chat")[0] == "FRESH"
    assert "frontend/src/components/panel.tsx" in pm.map_path("chat").read_text()
    (pm.tree_of("chat") / "frontend/src/components/panel.tsx").write_text("export const A = 2")
    assert pm.map_state("chat")[0] == "STALE"
    with pytest.raises(pm.StampRefused):
        stamp(pm, "chat")


def test_code_inventory_lists_pages_server_and_handles(pm):
    text = pm.code_inventory("artifact:demo")
    assert "`/preview/demo`" in text and "`/preview/demo/sub`" in text
    assert "`_server`" in text and "「保存する」" in text and "「見本」" in text


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


OWNER = "u-owner"
SB = FakeSb({
    "projects": [
        {"id": "p-branch", "room_id": "r-branch", "title": "ダン開発室: 枝", "metadata": {"hidden": True}, "origin_room_id": "r-lead", "user_id": OWNER},
        {"id": "p-lead", "room_id": "r-lead", "title": "ダン開発室", "metadata": {}, "origin_room_id": None, "user_id": OWNER},
        {"id": "p-two", "room_id": "r-two", "title": "二つ", "metadata": {}, "origin_room_id": None, "user_id": OWNER},
        {"id": "p-chat", "room_id": "r-chat", "title": "ふつうの部屋", "metadata": {}, "origin_room_id": None, "user_id": OWNER},
    ],
    "chat_artifact": [
        {"room_id": "r-lead", "project_id": "p-lead", "slug": "dev-lead", "updated_at": "2"},
        {"room_id": "r-two", "project_id": "p-two", "slug": "newer", "updated_at": "9"},
        {"room_id": "r-two", "project_id": "p-two", "slug": "demo", "updated_at": "1"},
    ],
})


def demo_map(pm, speak="右の画面の保存ボタン"):
    pm.map_path("artifact:demo").write_text(f"---\nplace: artifact:demo\nname: 見本の画面\nspeak: |\n  - {speak}\n---\n# 見本\n", encoding="utf-8")


def views(pm, *tabs):
    (pm.RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"
    data = {"tabs": {f"t{i}": {"user_id": OWNER, "slug": s, "frame": f, "visible": True, "ua": ua, "seen_at": now}
                     for i, (s, f, ua) in enumerate(tabs)}}
    (pm.RUNTIME_DIR / "live-views.json").write_text(json.dumps(data))


WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/155"
ANDROID = "Mozilla/5.0 (Linux; Android 17; SM-S931Q) Chrome/155"


def test_identify_place(pm):
    assert pm.identify_place("r-branch", sb=SB)["kind"] == "dev-lead-room"
    assert pm.identify_place("r-lead", sb=SB)["slugs"] == ["dev-lead"]
    assert pm.identify_place("r-chat", sb=SB)["kind"] == "chat"


def test_device_unknown_is_not_asserted(pm):
    ctx = pm.place_context("r-chat", sb=SB)
    assert "どの端末で読んでいるかは分からない" in ctx and "chat の話し方" in ctx


def test_device_comes_from_the_last_message(pm):
    pm.note_client("r-chat", ANDROID)
    assert "最後に書いた端末: スマホ" in pm.place_context("r-chat", sb=SB)
    pm.note_client("r-chat", WIN)
    assert "最後に書いた端末: PC" in pm.place_context("r-chat", sb=SB)


def test_selected_artifact_comes_from_the_owner_screen(pm):
    """10-25 確かめ役: 成果物が2つある部屋で、選んでいる方ではなく更新日時の新しい方の地図を渡していた。"""
    demo_map(pm)
    ctx = pm.place_context("r-two", sb=SB)
    assert "どの成果物を開いているかは分からない" in ctx and "右の画面の保存ボタン" not in ctx
    views(pm, ("demo", "frame", WIN))
    ctx = pm.place_context("r-two", sb=SB)
    assert "画面に今出ている成果物: demo（PC・成果物タブの中）" in ctx and "右の画面の保存ボタン" in ctx


def test_place_context_survives_db_failure(pm):
    class Broken:
        def table(self, name):
            raise RuntimeError("db down")
    assert pm.place_context("r-x", sb=Broken()) == ""


def test_cli_check_and_stamp(pm):
    env = {**os.environ, "DAN_ARTIFACTS_DIR": str(pm.ARTIFACTS_DIR), "DAN_PLACES_DIR": str(pm.PLACES_DIR)}
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts" / "place_map.py"), *a], capture_output=True, text=True, env=env)
    r = run("check", "demo")
    assert r.returncode == 2 and "[place_map] place=artifact:demo result=MISSING root=" in r.stdout
    assert run("draft", "demo", "見本").returncode == 1
    fill(pm)
    r = run("stamp", "demo")
    assert r.returncode == 0 and "result=FRESH" in r.stdout and pm.tree_of("artifact:demo").as_posix() in r.stdout
    (pm.ARTIFACTS_DIR / "demo" / "page.tsx").write_text("export default function P(){return <b>x</b>}")
    r = run("stamp", "demo")
    assert r.returncode == 1 and "stamp しませんでした" in r.stdout and "result=STALE" in r.stdout


def test_real_maps_parse():
    import app.agent.place_map as mod
    mod = importlib.reload(mod)
    for pid in ("chat", "artifact-tab", "dev-lead-room", "mobile"):
        m = mod.place_map(pid)
        assert m and m["meta"]["place"] == pid and m["meta"]["speak"].strip() and m["meta"].get("watches"), pid
        for head in ("## 中にある物", "## 行き方（みきさんから見て）", "## 道具で動かす", "## 落とし穴"):
            assert head in m["body"], (pid, head)
        assert mod.map_state(pid)[0] == "FRESH", pid


# --- 会話が長い部屋でも地図が残る（10-25 確かめ役の指摘 2） --------------------------------------------------------------

def test_long_room_keeps_the_place_on_reseed(monkeypatch):
    from app.agent import cli_runner
    long = "長い話。" * 400
    sb = FakeSb({
        "chat_messages": [{"room_id": "r", "sender_type": "human" if i % 2 else "ai", "content": long, "created_at": f"2026-10-25T{i:02d}"} for i in range(40)],
        "execution_events": [{"room_id": "r", "event_type": "tool_use", "tool_label": long[:300], "created_at": "x", "seq": i} for i in range(40)],
        "agent_runs": [],
        "projects": [],
    })
    monkeypatch.setattr("app.services.supabase_client.get_supabase_client", lambda: type("C", (), {"client": sb})())
    monkeypatch.setattr("app.agent.place_map.place_context", lambda room, project=None, sb=None: "<place>\nここは見本の場所\n</place>")
    state = cli_runner._build_room_state_context("r")
    reseed = cli_runner._build_reseed_context("r", max_chars=12000)
    assert state.startswith("<place>") and "ここは見本の場所" in state
    assert reseed.startswith("<place>") and "ここは見本の場所" in reseed and len(reseed) > 12000
    assert reseed.count("<place>") == 1


def test_common_map_ignores_artifacts_absent_from_this_tree(pm):
    """成果物は done-artifacts にあり、作業場所には無い。無い成果物のファイルは見ずに比べる（2026-10-26）。"""
    p = pm.map_path("dev-lead-room")
    p.write_text(p.read_text().replace("speak:", "watches:\n  - frontend/src/app/artifacts/demo/*.css\n  - frontend/src/components/*.tsx\nspeak:"), encoding="utf-8")
    stamp(pm, "dev-lead-room")
    import shutil
    shutil.rmtree(pm.ARTIFACTS_DIR / "demo")
    state, why = pm.map_state("dev-lead-room")
    assert state == "FRESH" and "demo" in why
    (pm.tree_of("dev-lead-room") / "frontend/src/components/panel.tsx").write_text("export const A = 3")
    assert pm.map_state("dev-lead-room")[0] == "STALE"
