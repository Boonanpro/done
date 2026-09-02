"""One-shot verification for the new dan_edit path: Dan must render a finished
video (not just a plan) and have it registered into content outputs.

Reuses the existing high-quality StyleUp UGC 01 instruction (brief + blur
annotations + reference sequence) and runs the real _run_production_job.
"""
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api import production_asset_routes as par

ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
CONTENT_ID = "68ab4fe4-6f96-4f72-b085-f818fae83a8d"
USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"

room_dir = par._room_dir(ROOM)
contents = json.loads((room_dir / "contents.json").read_text(encoding="utf-8"))
content = next(c for c in contents if c["id"] == CONTENT_ID)

jobs = json.loads((room_dir / "jobs.json").read_text(encoding="utf-8"))
prior = next(j for j in jobs if j["status"] == "done")  # 5ca2ba2d has full source_assets
source_assets = prior["instruction"]["source_assets"]

# Build instruction with the content's FULL timeline (annotations + audio policy + reference sequence)
instruction = {
    "mode": "dan_edit",
    "content_id": CONTENT_ID,
    "content_title": content["title"],
    "asset_ids": content["asset_ids"],
    "source_assets": source_assets,
    "brief": content["timeline"]["brief"],
    "workflow_preset": content["timeline"].get("workflow_preset", "video_ugc"),
    "timeline": content["timeline"],
}

job_id = str(uuid.uuid4())
now = datetime.now(timezone.utc).isoformat()
jobs.append({
    "id": job_id,
    "room_id": ROOM,
    "content_id": CONTENT_ID,
    "kind": "dan_execute",
    "status": "queued",
    "instruction": instruction,
    "result": {},
    "error": None,
    "created_at": now,
    "updated_at": now,
})
(room_dir / "jobs.json").write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"[test] starting dan_edit job {job_id}", flush=True)
par._run_production_job(ROOM, job_id, CONTENT_ID, instruction, USER_ID)
print(f"[test] job {job_id} finished", flush=True)

# Report outcome
jobs = json.loads((room_dir / "jobs.json").read_text(encoding="utf-8"))
job = next(j for j in jobs if j["id"] == job_id)
print("[test] status:", job["status"])
print("[test] error:", job.get("error"))
print("[test] result:", json.dumps(job.get("result", {}), ensure_ascii=False))
render = room_dir / "jobs" / job_id / f"{job_id}_dan_render.mp4"
print("[test] render exists:", render.exists(), "size:", render.stat().st_size if render.exists() else 0)
contents = json.loads((room_dir / "contents.json").read_text(encoding="utf-8"))
content = next(c for c in contents if c["id"] == CONTENT_ID)
print("[test] content outputs:", json.dumps(content.get("outputs", []), ensure_ascii=False))
