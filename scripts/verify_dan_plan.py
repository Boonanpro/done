"""E2E verification of the timeline-first dan_plan mode against the real CLI.
Creates a new content in the StyleUp room with the same 2 assets, posts a dan_plan
job (Dan emits decisions -> code assembles timeline, no MP4), polls to completion,
and prints the assembled sequence summary + Dan's decisions."""
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests
from app.services.auth_service import create_token_pair

USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"
EMAIL = "0aw325171@gmail.com"
ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
MAIN = "e22695c0-0b77-4413-a2e8-f585739243bc"
SCREEN = "535e2cc4-e200-40c3-b8f1-ade7c5cd3833"
BASE = "http://127.0.0.1:8000/api/v1/production-assets"
tp = create_token_pair(user_id=USER_ID, email=EMAIL)
H = {"Authorization": f"Bearer {tp.access_token}", "Content-Type": "application/json"}
C = {"done_access_token": tp.access_token, "done_refresh_token": tp.refresh_token}

def get(url):
    return requests.get(url, headers=H, cookies=C, timeout=30)
def post(url, body):
    return requests.post(url, headers=H, cookies=C, data=json.dumps(body), timeout=60)

# 1. source assets + brief
assets = get(f"{BASE}?room_id={ROOM}").json()
by_id = {a["id"]: a for a in assets}
src = [by_id[MAIN], by_id[SCREEN]]
contents = get(f"{BASE}/contents?room_id={ROOM}").json()
brief = ""
for c in contents:
    if (c.get("timeline") or {}).get("brief"):
        brief = c["timeline"]["brief"]; break
brief = brief or "この2素材でStyleUp紹介の縦型UGC。トーキングはカット・テロップ、画面操作はメインを下に小窓(ワイプ)で背景に画面、音声は全てメイン。初期設定の入力内容とSHUNの文字はぼかす。"
print(f"[e2e] using brief ({len(brief)} chars), assets: {[a['filename'] for a in src]}")

# 2. create content
content = post(f"{BASE}/contents", {
    "room_id": ROOM, "title": "StyleUp dan_plan E2E", "format": "9:16",
    "asset_ids": [MAIN, SCREEN],
    "timeline": {"brief": brief, "format": "9:16", "source_asset_ids": [MAIN, SCREEN], "annotations": []},
}).json()
cid = content["id"]
print(f"[e2e] content created: {cid}")

# 3. post dan_plan job (mirrors frontend createContent instruction)
instruction = {
    "mode": "dan_plan", "content_id": cid, "content_title": content["title"],
    "asset_ids": [MAIN, SCREEN],
    "source_assets": [{"id": a["id"], "kind": a["kind"], "filename": a.get("filename"),
                       "local_path": a.get("local_path"), "proxy_path": a.get("proxy_path"),
                       "source_type": a.get("source_type"), "metadata": a.get("metadata")} for a in src],
    "brief": brief,
    "timeline": {"brief": brief, "format": "9:16", "source_asset_ids": [MAIN, SCREEN], "annotations": []},
}
job = post(f"{BASE}/jobs", {"room_id": ROOM, "content_id": cid, "instruction": instruction}).json()
jid = job["id"]
print(f"[e2e] dan_plan job posted: {jid} -- polling (up to 20 min)...")

# 4. poll
deadline = 1200
t0 = time.time()
status = "running"
while time.time() - t0 < deadline:
    time.sleep(15)
    jobs = get(f"{BASE}/jobs?room_id={ROOM}&content_id={cid}").json()
    j = next((x for x in jobs if x["id"] == jid), None)
    status = (j or {}).get("status")
    ev = get(f"{BASE}/jobs/{jid}/events?room_id={ROOM}")
    last = ""
    try:
        lines = [l for l in ev.text.splitlines() if l.strip()]
        last = lines[-1][:90] if lines else ""
    except Exception:
        pass
    print(f"[e2e] +{int(time.time()-t0)}s status={status}  {last}")
    if status in ("done", "failed"):
        break

print(f"\n[e2e] FINAL status={status}")
# 5. inspect assembled sequence
content = get(f"{BASE}/contents/{cid}?room_id={ROOM}").json() if False else next((c for c in get(f"{BASE}/contents?room_id={ROOM}").json() if c["id"] == cid), {})
seq = (content.get("timeline") or {}).get("sequence") or {}
print("[e2e] sequence tracks:", [(t.get("type"), len(t.get("clips", []))) for t in seq.get("tracks", [])])
print("[e2e] duration:", seq.get("duration"), "generated_by:", seq.get("generated_by"))
for t in seq.get("tracks", []):
    if t.get("type") == "caption":
        for c in t.get("clips", []):
            print(f"   テロップ {c.get('timeline_start')}-{c.get('timeline_end')}: {(c.get('text') or '')[:30]}")
    if t.get("type") in ("video", "overlay"):
        for c in t.get("clips", []):
            print(f"   {t['type']}/{c.get('role')}/{c.get('composition')} tl {c.get('timeline_start')}-{c.get('timeline_end')} src {c.get('source_start')}-{c.get('source_end')}")
print("[e2e] done")
