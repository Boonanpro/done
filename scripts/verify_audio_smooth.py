"""Audio warble (gobogobo) fix: during steady playback within a clip, the audio element must
NOT be re-seeked backward (frequent seeks of a playing element = the underwater/warble sound).
Play a 20s A/V clip, sample the audio element's currentTime at ~60ms, and assert it advances
monotonically with essentially zero backward steps."""
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

seq = {"format": "9:16", "duration": 20.0, "tracks": [
    {"id": "tv", "type": "video", "clips": [{"id": "V1", "asset_id": MAIN, "track": "video", "layer": 0,
        "timeline_start": 0, "timeline_end": 20, "source_start": 0, "source_end": 20,
        "composition": "fullscreen", "link_id": "L1"}]},
    {"id": "ta", "type": "audio", "clips": [{"id": "A1", "asset_id": MAIN, "track": "audio", "layer": 0,
        "timeline_start": 0, "timeline_end": 20, "source_start": 0, "source_end": 20,
        "role": "dialogue", "link_id": "L1"}]}]}

content = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, data=json.dumps(
    {"room_id": ROOM, "title": "AUDIO SMOOTH TEST", "format": "9:16", "asset_ids": [MAIN],
     "timeline": {"format": "9:16", "source_asset_ids": [MAIN], "annotations": []}})).json()
cid = content["id"]
P._update_content(ROOM, cid, {"timeline": {"sequence": seq, "annotations": []}})
print("throwaway content:", cid[:8])

ok = True
def check(name, cond, detail=""):
    global ok
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
    ok = ok and cond

try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel="chrome", args=["--autoplay-policy=no-user-gesture-required"])
        ctx = b.new_context(viewport={"width": 1500, "height": 950})
        ctx.add_cookies([{"name": "done_access_token", "value": tp.access_token, "url": WEB},
                         {"name": "done_refresh_token", "value": tp.refresh_token, "url": WEB}])
        ctx.add_init_script(f"window.localStorage.setItem('done-token', {tp.access_token!r});")
        page = ctx.new_page()
        page.goto(f"{WEB}/production-workspace?room_id={ROOM}&content_id={cid}", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(8000)
        page.mouse.click(750, 400)
        page.keyboard.press("Space")
        page.wait_for_timeout(1200)
        # sample the audio element's currentTime densely
        cts = []
        for _ in range(50):
            page.wait_for_timeout(60)
            ct = page.evaluate("""() => { const a = Array.from(document.querySelectorAll('video'))
                .filter(v => v.style.display==='none' && /e22695c0/.test(v.currentSrc||v.src||'') && !v.paused);
                return a.length ? a.map(v=>v.currentTime) : null; }""")
            if ct:
                cts.append(ct)
        b.close()

    # flatten the furthest-along element per sample (the audio playhead)
    series = [max(s) for s in cts if s]
    backward = sum(1 for i in range(1, len(series)) if series[i] < series[i-1] - 0.03)
    print(f"samples={len(series)}  span={series[0] if series else 0:.2f}->{series[-1] if series else 0:.2f}  backward_steps={backward}")
    check("playback advanced", len(series) > 5 and series[-1] - series[0] > 0.8)
    check("no warble (~0 backward seeks during steady playback)", backward <= 1, f"backward steps={backward}")
finally:
    cpath = P._room_dir(ROOM) / "contents.json"
    data = json.loads(cpath.read_text(encoding="utf-8"))
    data = [c for c in data if c["id"] != cid]
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[cleanup] throwaway content removed")

print("\nAUDIO SMOOTH:", "ALL PASS" if ok else "FAILURES")
