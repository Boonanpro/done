"""#3 lip-sync: a dropped-style A/V-linked pair (video + audio, same asset & source) must stay
in sync during playback. Isolated content with one fullscreen video clip + linked audio clip
(both MAIN, source 0-20). Play, sample the two hidden <video> elements' currentTime over a few
seconds, and assert they advance and stay within ~0.12s of each other (locked, not drifting)."""
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
    {"id": "tk_v", "type": "video", "clips": [{"id": "v1", "asset_id": MAIN, "track": "video", "layer": 0,
        "timeline_start": 0, "timeline_end": 20, "source_start": 0, "source_end": 20,
        "composition": "fullscreen", "link_id": "lkAV", "label": "v"}]},
    {"id": "tk_a", "type": "audio", "clips": [{"id": "a1", "asset_id": MAIN, "track": "audio", "layer": 0,
        "timeline_start": 0, "timeline_end": 20, "source_start": 0, "source_end": 20,
        "role": "dialogue", "link_id": "lkAV", "label": "a"}]}]}

content = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, data=json.dumps(
    {"room_id": ROOM, "title": "AVSYNC TEST (throwaway)", "format": "9:16", "asset_ids": [MAIN],
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

        def sample():
            # the two hidden <video> elements (video layer + audio) both use the MAIN proxy
            return page.evaluate("""() => Array.from(document.querySelectorAll('video'))
                .filter(v => (v.style.display === 'none') && /e22695c0/.test(v.currentSrc || v.src || ''))
                .map(v => ({ ct: Number(v.currentTime.toFixed(3)), paused: v.paused }))""")

        # start playback (Space toggles play in the editor)
        page.mouse.click(750, 400)  # focus the editor area
        page.keyboard.press("Space")
        page.wait_for_timeout(1500)
        samples = []
        for _ in range(4):
            page.wait_for_timeout(700)
            samples.append(sample())
        print("samples (video/audio currentTime):", samples)
        b.close()

    # analyse: need at least 2 elements, both advancing, and within 0.12s of each other
    valid = [s for s in samples if len(s) >= 2]
    check("two hidden MAIN media elements present", bool(valid))
    if valid:
        advanced = any(max(e["ct"] for e in s) > 0.5 for s in valid)
        check("playback advanced (currentTime moved)", advanced)
        gaps = [abs(s[0]["ct"] - s[1]["ct"]) for s in valid if len(s) >= 2]
        worst = max(gaps) if gaps else 99
        check("video & audio stay locked (<0.12s apart)", worst < 0.12, f"worst gap={worst:.3f}s")
finally:
    cpath = P._room_dir(ROOM) / "contents.json"
    data = json.loads(cpath.read_text(encoding="utf-8"))
    data = [c for c in data if c["id"] != cid]
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[cleanup] throwaway content removed")

print("\nA/V SYNC:", "ALL PASS" if ok else "FAILURES (note: headless audio playback can be unreliable)")
