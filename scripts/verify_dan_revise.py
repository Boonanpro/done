"""E2E for Stage 3 partial edit (dan_revise): ask Dan to change ONE caption (region-scoped)
and assert every OTHER clip is preserved byte-identical. Snapshots the timeline before,
posts a dan_revise job scoped to one caption's time range, polls, then diffs."""
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests
from app.services.auth_service import create_token_pair

USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"
EMAIL = "0aw325171@gmail.com"
ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
BASE = "http://127.0.0.1:8000/api/v1/production-assets"
tp = create_token_pair(user_id=USER_ID, email=EMAIL)
H = {"Authorization": f"Bearer {tp.access_token}", "Content-Type": "application/json"}
C = {"done_access_token": tp.access_token}

def get(u): return requests.get(u, headers=H, cookies=C, timeout=30)
def post(u, b): return requests.post(u, headers=H, cookies=C, data=json.dumps(b), timeout=60)

contents = get(f"{BASE}/contents?room_id={ROOM}").json()
ct = next(c for c in contents if c["id"].startswith("8a429e2b"))
cid = ct["id"]
seq_before = ct["timeline"]["sequence"]

def clip_map(seq):
    return {c["id"]: c for t in seq["tracks"] for c in t.get("clips", [])}

before = clip_map(seq_before)
# pick the 2nd caption to target
caps = [c for t in seq_before["tracks"] if t["type"] == "caption" for c in t["clips"]]
target = caps[1]
print(f"[rev] target caption {target['id']}: '{target['text'][:20]}' ts {target['timeline_start']}-{target['timeline_end']}")
print(f"[rev] total clips before: {len(before)}")

assets = get(f"{BASE}?room_id={ROOM}").json()
src = [a for a in assets if a["id"] in (ct.get("asset_ids") or [])]
instruction = {
    "mode": "dan_revise", "content_id": cid, "content_title": ct["title"],
    "asset_ids": ct.get("asset_ids"),
    "source_assets": [{"id": a["id"], "kind": a["kind"], "filename": a.get("filename"),
                       "local_path": a.get("local_path"), "proxy_path": a.get("proxy_path")} for a in src],
    "revision_text": "このテロップの文字を赤くして、文末に「！」を足して",
    "revision_regions": [{"intent": "comment", "start": target["timeline_start"], "end": target["timeline_end"],
                          "track": "caption", "note": "このテロップを赤く＋！"}],
    "timeline": {**ct["timeline"], "format": ct.get("format", "9:16"), "annotations": []},
}
job = post(f"{BASE}/jobs", {"room_id": ROOM, "content_id": cid, "instruction": instruction}).json()
jid = job["id"]
print(f"[rev] dan_revise job {jid} posted, polling...")

status = "running"; t0 = time.time()
while time.time() - t0 < 900:
    time.sleep(15)
    jobs = get(f"{BASE}/jobs?room_id={ROOM}&content_id={cid}").json()
    j = next((x for x in jobs if x["id"] == jid), {})
    status = j.get("status")
    ev = get(f"{BASE}/jobs/{jid}/events?room_id={ROOM}")
    last = (ev.text.splitlines() or [""])[-1][:80] if ev.text.strip() else ""
    print(f"  +{int(time.time()-t0)}s {status} {last}")
    if status in ("done", "failed"):
        break

print(f"[rev] FINAL {status}")
ct2 = next(c for c in get(f"{BASE}/contents?room_id={ROOM}").json() if c["id"] == cid)
after = clip_map(ct2["timeline"]["sequence"])
print(f"[rev] total clips after: {len(after)}")

# 1) target changed
ta = after.get(target["id"])
print(f"[rev] target after: text='{(ta or {}).get('text','')[:24]}' style={(ta or {}).get('style')}")
# 2) all OTHER clips identical
changed_others = []
for cid_, c in before.items():
    if cid_ == target["id"]:
        continue
    if json.dumps(after.get(cid_), sort_keys=True, ensure_ascii=False) != json.dumps(c, sort_keys=True, ensure_ascii=False):
        changed_others.append(cid_)
print(f"[rev] OUT-OF-SCOPE clips changed: {len(changed_others)} (expect 0) {changed_others[:5]}")
print("[rev] RESULT:", "PASS — partial edit preserved everything else" if not changed_others and ta else "CHECK")
