"""Slice 2: cut-adjust UI. Throwaway content WITH decisions + an initial sequence (assembled at
0.45). Open it, move the 無音しきい値 slider to 0.25, click 'この設定で再カット' (accept the confirm
dialog), and assert the content's persisted sequence.cut_params.silence_threshold became 0.25."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests
from app.services.auth_service import create_token_pair
from app.api import production_asset_routes as P

ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
MAIN = "e22695c0-0b77-4413-a2e8-f585739243bc"
APIB = "http://127.0.0.1:8000/api/v1/production-assets"
WEB = "http://127.0.0.1:3000"
tp = create_token_pair(user_id="2582a188-ff24-4a4f-b989-6063034d90b2", email="0aw325171@gmail.com")
H = {"Authorization": f"Bearer {tp.access_token}", "Content-Type": "application/json"}
C = {"done_access_token": tp.access_token}

# build decisions (keep all segments) + initial sequence at 0.45
assets = P._read_assets(ROOM)
main = next(a for a in assets if str(a.get("id")) == MAIN)
src_assets = [{"id": MAIN, "kind": main.get("kind"), "filename": main.get("filename"),
               "local_path": main.get("local_path"), "proxy_path": main.get("proxy_path"), "metadata": main.get("metadata")}]
transcripts = P._run_audio_analysis(ROOM, "recut_ui", src_assets)
segs = [s for t in transcripts.values() for s in (t.get("segments") or [])]
decisions = {"spine": [{"segment_id": s["id"]} for s in segs], "cuts": [], "silence_threshold": 0.45}
seq0 = P._assemble_sequence_from_decisions(dict(decisions), transcripts, ROOM, "9:16")

content = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, data=json.dumps(
    {"room_id": ROOM, "title": "RECUT UI TEST", "format": "9:16", "asset_ids": [MAIN],
     "timeline": {"format": "9:16", "source_asset_ids": [MAIN], "annotations": [], "decisions": decisions, "sequence": seq0}})).json()
cid = content["id"]
print("throwaway content:", cid[:8], "| initial cut_params:", seq0.get("cut_params"))

ok = True
def check(name, cond, detail=""):
    global ok
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
    ok = ok and cond

try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel="chrome")
        ctx = b.new_context(viewport={"width": 1500, "height": 950})
        ctx.add_cookies([{"name": "done_access_token", "value": tp.access_token, "url": WEB},
                         {"name": "done_refresh_token", "value": tp.refresh_token, "url": WEB}])
        ctx.add_init_script(f"window.localStorage.setItem('done-token', {tp.access_token!r});")
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())  # accept the "手動編集はリセット" confirm
        page.goto(f"{WEB}/production-workspace?room_id={ROOM}&content_id={cid}", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(8000)

        panel = page.query_selector("text=カット調整（無音・間）")
        check("cut-adjust panel present", bool(panel))
        slider = page.query_selector("input[type='range'][min='0.2']")
        check("silence-threshold slider present", bool(slider))
        if slider:
            page.evaluate("""() => {
              const s = document.querySelector("input[type='range'][min='0.2']");
              const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
              setter.call(s, '0.25'); s.dispatchEvent(new Event('input', {bubbles:true})); s.dispatchEvent(new Event('change', {bubbles:true}));
            }""")
            page.wait_for_timeout(300)
        btn = page.query_selector("button:has-text('この設定で再カット')")
        check("re-cut button present", bool(btn))
        if btn:
            btn.click()
            page.wait_for_timeout(4000)  # recut runs (cached analysis) + loadAll
        b.close()

    ct = next(c for c in requests.get(f"{APIB}/contents?room_id={ROOM}", headers=H, cookies=C, timeout=30).json() if c["id"] == cid)
    cp = (ct.get("timeline") or {}).get("sequence", {}).get("cut_params", {})
    print("persisted cut_params after re-cut:", cp)
    check("re-cut applied & persisted threshold 0.25", cp.get("silence_threshold") == 0.25, f"threshold={cp.get('silence_threshold')}")
finally:
    cpath = P._room_dir(ROOM) / "contents.json"
    data = json.loads(cpath.read_text(encoding="utf-8"))
    data = [c for c in data if c["id"] != cid]
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[cleanup] throwaway content removed")

print("\nRECUT UI:", "ALL PASS" if ok else "FAILURES")
