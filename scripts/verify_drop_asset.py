"""Slice 5: verify drag-drop of a source asset onto the timeline. Isolated throwaway content
with the MAIN video asset selected and a tiny 2-clip seed sequence. Simulates an HTML5
drag from the material thumbnail onto a visual lane (shared DataTransfer dispatch, which
exercises the real onDragStart/onDrop handlers) and asserts a 3rd clip was inserted at the
drop time with asset_id=MAIN. Throwaway content is deleted afterward."""
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

def vclip(i, s, e):
    return {"id": f"seed_{i}", "asset_id": MAIN, "track": "video", "layer": 0,
            "timeline_start": s, "timeline_end": e, "source_start": s, "source_end": e,
            "composition": "fullscreen", "label": f"seed{i}"}

seq = {"format": "9:16", "duration": 6.0, "tracks": [
    {"id": "tk_v", "type": "video", "clips": [vclip("A", 0, 3), vclip("B", 3, 6)]}]}

content = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, data=json.dumps(
    {"room_id": ROOM, "title": "DROP TEST (throwaway)", "format": "9:16", "asset_ids": [MAIN],
     "timeline": {"format": "9:16", "source_asset_ids": [MAIN], "annotations": []}})).json()
cid = content["id"]
P._update_content(ROOM, cid, {"timeline": {"sequence": seq, "annotations": []}})
print("throwaway content:", cid[:8])

def read_video_clips():
    ct = next(c for c in requests.get(f"{APIB}/contents?room_id={ROOM}", headers=H, cookies=C, timeout=30).json() if c["id"] == cid)
    s = (ct.get("timeline") or {}).get("sequence") or {}
    vids = [c for t in s.get("tracks", []) if t["type"] == "video" for c in t.get("clips", [])]
    auds = [c for t in s.get("tracks", []) if t["type"] == "audio" for c in t.get("clips", [])]
    return vids, auds, s.get("duration")

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
        page.goto(f"{WEB}/production-workspace?room_id={ROOM}&content_id={cid}", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(8000)

        # material thumbnail is draggable (title set only for video assets)
        drag_src = page.query_selector("[title='ドラッグでタイムラインに追加']")
        check("material thumbnail is draggable", bool(drag_src))

        # simulate HTML5 DnD with a shared DataTransfer so onDragStart's setData reaches onDrop
        res = page.evaluate("""() => {
          const src = document.querySelector("[title='ドラッグでタイムラインに追加']");
          const lanes = Array.from(document.querySelectorAll('div')).filter(e => {
            const c=(e.className||'').toString();
            return c.includes('bg-neutral-900') && e.getBoundingClientRect().width > 300; });
          const lane = lanes[0];
          if (!src || !lane) return {ok:false};
          const dt = new DataTransfer();
          src.dispatchEvent(new DragEvent('dragstart', {bubbles:true, cancelable:true, dataTransfer:dt}));
          const r = lane.getBoundingClientRect();
          const clientX = r.left + r.width*0.5, clientY = r.top + r.height/2;
          lane.dispatchEvent(new DragEvent('dragover', {bubbles:true, cancelable:true, dataTransfer:dt, clientX, clientY}));
          lane.dispatchEvent(new DragEvent('drop', {bubbles:true, cancelable:true, dataTransfer:dt, clientX, clientY}));
          return {ok:true, payload: dt.getData('application/x-dan-asset'), dropFracApprox: 0.5};
        }""")
        print("dispatch result:", res)
        page.wait_for_timeout(1500)
        b.close()

    clips, auds, dur = read_video_clips()
    print("video clips after drop:", [(c.get("id"), c.get("timeline_start"), c.get("timeline_end"), str(c.get("asset_id"))[:8]) for c in clips])
    print("audio clips after drop:", [(c.get("id"), c.get("timeline_start"), c.get("timeline_end"), c.get("link_id")) for c in auds])
    new = [c for c in clips if not str(c.get("id", "")).startswith("seed_")]
    check("a new clip was inserted (2 -> 3)", len(clips) == 3 and len(new) == 1)
    if new:
        nc = new[0]
        check("new clip references the dropped asset (MAIN)", nc.get("asset_id") == MAIN)
        check("new clip placed at the drop time (mid-timeline, not 0)", nc["timeline_start"] > 1.0,
              f"start={nc['timeline_start']}")
        check("new clip has positive length", nc["timeline_end"] > nc["timeline_start"])
        check("new clip is on the video track / fullscreen-or-overlay",
              nc.get("track") == "video" and nc.get("composition") in ("fullscreen", "overlay"))
        # the dropped video must bring its AUDIO too, A/V-linked
        check("an audio clip was also added", len(auds) == 1)
        if auds:
            ac = auds[0]
            check("audio clip is A/V-linked to the video (shared link_id)",
                  bool(ac.get("link_id")) and ac.get("link_id") == nc.get("link_id"),
                  f"v={nc.get('link_id')} a={ac.get('link_id')}")
            check("audio clip time-aligned with the video",
                  abs(ac["timeline_start"] - nc["timeline_start"]) < 0.05 and abs(ac["timeline_end"] - nc["timeline_end"]) < 0.05)
finally:
    cpath = P._room_dir(ROOM) / "contents.json"
    data = json.loads(cpath.read_text(encoding="utf-8"))
    data = [c for c in data if c["id"] != cid]
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[cleanup] throwaway content removed")

print("\nDROP ASSET:", "ALL PASS" if ok else "FAILURES")
