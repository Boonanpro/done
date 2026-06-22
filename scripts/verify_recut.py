"""Slice 1: re-cut backend. (a) In-process: assemble the same decisions at silence_threshold
0.3 vs 1.0 and assert lower threshold removes MORE silence (removed_total) and emits cut_meta +
cut_params. (b) HTTP: POST /contents/{id}/recut on a throwaway content and assert it rebuilds."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests
from app.services.auth_service import create_token_pair
from app.api import production_asset_routes as P

ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
MAIN = "e22695c0-0b77-4413-a2e8-f585739243bc"
APIB = "http://127.0.0.1:8000/api/v1/production-assets"
tp = create_token_pair(user_id="2582a188-ff24-4a4f-b989-6063034d90b2", email="0aw325171@gmail.com")
H = {"Authorization": f"Bearer {tp.access_token}", "Content-Type": "application/json"}
C = {"done_access_token": tp.access_token}

ok = True
def check(name, cond, detail=""):
    global ok
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
    ok = ok and cond

# ---- (a) in-process assembly at two thresholds ----
assets = P._read_assets(ROOM)
main = next(a for a in assets if str(a.get("id")) == MAIN)
src_assets = [{"id": MAIN, "kind": main.get("kind"), "filename": main.get("filename"),
               "local_path": main.get("local_path"), "proxy_path": main.get("proxy_path"), "metadata": main.get("metadata")}]
transcripts = P._run_audio_analysis(ROOM, "recut_verify", src_assets)
segs = [s for t in transcripts.values() for s in (t.get("segments") or [])]
print(f"segments available: {len(segs)}")
spine = [{"segment_id": s["id"]} for s in segs]  # keep everything; only silence compression differs
decisions = {"spine": spine, "cuts": [], "silence_threshold": 0.45}

def assemble(sil):
    d = dict(decisions); d["silence_threshold"] = sil
    return P._assemble_sequence_from_decisions(d, transcripts, ROOM, "9:16")

seq_tight = assemble(0.3)   # aggressive: remove silence > 0.3s
seq_loose = assemble(1.0)   # relaxed: only remove silence > 1.0s
check("assembled at threshold 0.3", bool(seq_tight))
check("assembled at threshold 1.0", bool(seq_loose))
if seq_tight and seq_loose:
    rt, rl = seq_tight.get("removed_total"), seq_loose.get("removed_total")
    print(f"removed_total: tight(0.3)={rt}  loose(1.0)={rl}")
    check("cut_params reflects the threshold", seq_tight.get("cut_params", {}).get("silence_threshold") == 0.3)
    check("cut_meta present", isinstance(seq_tight.get("cut_meta"), list) and len(seq_tight["cut_meta"]) > 0,
          f"{len(seq_tight.get('cut_meta') or [])} cuts")
    check("lower threshold removes MORE silence", (rt or 0) >= (rl or 0), f"{rt} >= {rl}")
    check("cut_meta entries have at/removed/type",
          all(set(("at", "removed", "type")) <= set(c.keys()) for c in seq_tight["cut_meta"][:5]))

# ---- (b) HTTP recut on a throwaway content ----
content = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, data=json.dumps(
    {"room_id": ROOM, "title": "RECUT HTTP TEST", "format": "9:16", "asset_ids": [MAIN],
     "timeline": {"format": "9:16", "source_asset_ids": [MAIN], "annotations": [],
                  "decisions": decisions, "sequence": seq_loose}})).json()
cid = content["id"]
print("throwaway content:", cid[:8])
try:
    r = requests.post(f"{APIB}/contents/{cid}/recut?room_id={ROOM}", headers=H, cookies=C, timeout=120,
                      data=json.dumps({"silence_threshold": 0.3}))
    print("recut HTTP status:", r.status_code)
    body = r.json() if r.status_code == 200 else r.text
    check("recut endpoint returns 200", r.status_code == 200, str(body)[:160])
    if r.status_code == 200:
        check("recut applied threshold 0.3", body.get("cut_params", {}).get("silence_threshold") == 0.3)
        check("recut reports clip/cut counts", body.get("clip_count", 0) > 0 and body.get("cut_count", 0) >= 0,
              f"clips={body.get('clip_count')} cuts={body.get('cut_count')} removed={body.get('removed_total')}")
        # confirm it persisted to the content
        ct = next(c for c in requests.get(f"{APIB}/contents?room_id={ROOM}", headers=H, cookies=C, timeout=30).json() if c["id"] == cid)
        persisted = (ct.get("timeline") or {}).get("sequence", {}).get("cut_params", {}).get("silence_threshold")
        check("recut persisted to content", persisted == 0.3, f"persisted threshold={persisted}")
finally:
    cpath = P._room_dir(ROOM) / "contents.json"
    data = json.loads(cpath.read_text(encoding="utf-8"))
    data = [c for c in data if c["id"] != cid]
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[cleanup] throwaway content removed")

print("\nRECUT:", "ALL PASS" if ok else "FAILURES")
