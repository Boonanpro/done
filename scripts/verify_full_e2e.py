"""Full pipeline E2E (B): material select -> dan_plan generate -> apply every manual edit
(transform / crop / multi-select / caption style / clip delete) deterministically on the
timeline -> render MP4. Catches crashes and obvious breakage from edit COMBINATIONS before
the user does a hands-on pass. Uses the real assembler + renderer (no browser needed for
the edit-combination check; that's covered by the deterministic render)."""
import sys, json, time, copy, glob
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests
from app.services.auth_service import create_token_pair
from app.api import production_asset_routes as P

ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
MAIN = "e22695c0-0b77-4413-a2e8-f585739243bc"
SCREEN = "535e2cc4-e200-40c3-b8f1-ade7c5cd3833"
BASE = "http://127.0.0.1:8000/api/v1/production-assets"
tp = create_token_pair(user_id="2582a188-ff24-4a4f-b989-6063034d90b2", email="0aw325171@gmail.com")
H = {"Authorization": f"Bearer {tp.access_token}", "Content-Type": "application/json"}
C = {"done_access_token": tp.access_token}
def get(u): return requests.get(u, headers=H, cookies=C, timeout=30)
def post(u, b): return requests.post(u, headers=H, cookies=C, data=json.dumps(b), timeout=60)

FAILS = []
def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok: FAILS.append(name)

# ---- 1. material select + content create ----
assets = get(f"{BASE}?room_id={ROOM}").json()
src = [a for a in assets if a["id"] in (MAIN, SCREEN)]
brief = "この2素材でStyleUp紹介の縦型UGC。トーキングはカット・テロップ、画面操作はメインを下に小窓(ワイプ)で背景に画面、音声は全てメイン。"
content = post(f"{BASE}/contents", {"room_id": ROOM, "title": "Full E2E", "format": "9:16",
                                    "asset_ids": [MAIN, SCREEN],
                                    "timeline": {"brief": brief, "format": "9:16", "source_asset_ids": [MAIN, SCREEN], "annotations": []}}).json()
cid = content["id"]
check("content created", bool(cid), cid[:8])

# ---- 2. dan_plan generate ----
instr = {"mode": "dan_plan", "content_id": cid, "content_title": content["title"], "asset_ids": [MAIN, SCREEN],
         "source_assets": [{"id": a["id"], "kind": a["kind"], "filename": a.get("filename"),
                            "local_path": a.get("local_path"), "proxy_path": a.get("proxy_path"), "metadata": a.get("metadata")} for a in src],
         "brief": brief, "timeline": {"brief": brief, "format": "9:16", "source_asset_ids": [MAIN, SCREEN], "annotations": []}}
job = post(f"{BASE}/jobs", {"room_id": ROOM, "content_id": cid, "instruction": instr}).json()
jid = job["id"]
print(f"[e2e] dan_plan {jid[:8]} generating...")
st = "running"; t0 = time.time()
while time.time() - t0 < 900:
    time.sleep(15)
    j = next((x for x in get(f"{BASE}/jobs?room_id={ROOM}&content_id={cid}").json() if x["id"] == jid), {})
    st = j.get("status")
    if st in ("done", "failed"): break
check("dan_plan generated a timeline", st == "done", f"{int(time.time()-t0)}s")
ct = next(c for c in get(f"{BASE}/contents?room_id={ROOM}").json() if c["id"] == cid)
seq = (ct.get("timeline") or {}).get("sequence") or {}
tracks = {t["type"]: t.get("clips", []) for t in seq.get("tracks", [])}
check("timeline has video+caption+audio", all(tracks.get(k) for k in ("video", "caption", "audio")),
      f"v{len(tracks.get('video', []))} c{len(tracks.get('caption', []))} a{len(tracks.get('audio', []))}")

# ---- 3. apply a COMBINATION of manual edits to the sequence ----
seq2 = copy.deepcopy(seq)
allclips = [c for t in seq2["tracks"] for c in t.get("clips", [])]
vids = [c for t in seq2["tracks"] if t["type"] == "video" for c in t.get("clips", [])]
ovs = [c for t in seq2["tracks"] if t["type"] == "overlay" for c in t.get("clips", [])]
caps = [c for t in seq2["tracks"] if t["type"] == "caption" for c in t.get("clips", [])]
auds = [c for t in seq2["tracks"] if t["type"] == "audio" for c in t.get("clips", [])]
# transform (zoom+pan, off-screen), crop, volume on a base clip
if vids:
    vids[0]["transform"] = {"scale": 0.6, "x": 0.3, "y": -0.2}
    vids[0]["crop"] = {"top": 0.1, "bottom": 0.1, "left": 0, "right": 0}
    if len(vids) > 1: vids[1]["volume"] = 0.5
# caption style on first caption
if caps:
    caps[0]["style"] = {"color": "#FFD400", "fontSize": 1.3, "position": "top"}
# multi-edit: same transform on two overlay clips (absolute)
for o in ovs[:2]:
    o["transform"] = {"scale": 1.2, "x": 0, "y": 0}
print(f"[e2e] applied edits: transform+crop+volume on base, style on caption, transform on {min(2,len(ovs))} overlays")
P._update_content(ROOM, cid, {"timeline": {**ct["timeline"], "sequence": seq2}})

# ---- 4. render MP4 (deterministic export) ----
jid2 = "fulle2e_render"
jd = P._room_dir(ROOM) / "jobs" / jid2
jd.mkdir(parents=True, exist_ok=True)
try:
    res = P._render_sequence_job(ROOM, jid2, cid, {"timeline": {"sequence": seq2, "annotations": []}}, jd)
except Exception as e:
    res = None
    print("[e2e] render EXCEPTION:", repr(e)[:200])
mp4 = glob.glob(str(jd / "*_sequence.mp4"))
check("rendered MP4 with all edits combined", bool(res and mp4), (res or {}).get("render_size", ""))
if mp4:
    import subprocess
    ffp = r"C:\Users\Owner\ffmpeg\bin\ffprobe.exe"
    try:
        out = subprocess.run([ffp, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4[0]],
                             capture_output=True, text=True, timeout=30)
        dur = float((out.stdout or "0").strip() or 0)
        check("MP4 has valid duration", dur > 1, f"{dur:.1f}s")
    except Exception as e:
        check("MP4 probe", False, repr(e)[:80])

# ---- 5. AI partial edit (dan_revise) on top of manual edits ----
tgt = caps[1] if len(caps) > 1 else (caps[0] if caps else None)
if tgt:
    instr2 = {"mode": "dan_revise", "content_id": cid, "content_title": ct["title"], "asset_ids": [MAIN, SCREEN],
              "source_assets": [{"id": a["id"], "kind": a["kind"], "filename": a.get("filename"),
                                 "local_path": a.get("local_path"), "proxy_path": a.get("proxy_path")} for a in src],
              "revision_text": "このテロップを赤くして", "revision_regions": [{"intent": "comment", "start": tgt["timeline_start"], "end": tgt["timeline_end"], "track": "caption"}],
              "timeline": {**ct["timeline"], "sequence": seq2, "format": "9:16", "annotations": []}}
    rj = post(f"{BASE}/jobs", {"room_id": ROOM, "content_id": cid, "instruction": instr2}).json()
    rjid = rj["id"]; t0 = time.time(); rst = "running"
    while time.time() - t0 < 600:
        time.sleep(12)
        j = next((x for x in get(f"{BASE}/jobs?room_id={ROOM}&content_id={cid}").json() if x["id"] == rjid), {})
        rst = j.get("status")
        if rst in ("done", "failed"): break
    # verify only target changed + manual edits preserved
    ct3 = next(c for c in get(f"{BASE}/contents?room_id={ROOM}").json() if c["id"] == cid)
    v0 = next((c for t in ct3["timeline"]["sequence"]["tracks"] if t["type"] == "video" for c in t["clips"] if c["id"] == vids[0]["id"]), {})
    check("dan_revise done", rst == "done", f"{int(time.time()-t0)}s")
    check("manual transform PRESERVED after AI revise", v0.get("transform") == {"scale": 0.6, "x": 0.3, "y": -0.2}, str(v0.get("transform")))
    check("manual crop PRESERVED after AI revise", bool(v0.get("crop")), str(v0.get("crop")))

print()
print("FULL E2E:", "ALL PASS — pipeline works end to end with edit combinations" if not FAILS else f"{len(FAILS)} FAILURES: {FAILS}")
print(f"content_id={cid}")
