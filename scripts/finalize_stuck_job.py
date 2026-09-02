"""Manually finalize a dan_edit job whose CLI produced all deliverables
(render mp4 + dan_timeline.json) but whose completion handler never fired,
leaving the job stuck in 'running' and the content timeline empty.

Replicates exactly what the sandbox worker does after _build_dan_timeline:
register the render as an output asset, write the sequence into the content
timeline, and mark the job done. Read-modify of the room's JSON ledgers only.
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api import production_asset_routes as P

ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
CONTENT = "e2d8dda0-240d-4c45-9451-ffa6f5ad3d8c"
JOB = "0f25ca78-9ad6-4535-8aa4-113b42faa596"

job_dir = P._room_dir(ROOM) / "jobs" / JOB
instruction_path = job_dir / "timeline_instruction.json"
dan_timeline_path = job_dir / "dan_timeline.json"
dan_render_path = job_dir / f"{JOB}_dan_render.mp4"

assert instruction_path.exists(), "no instruction"
assert dan_timeline_path.exists(), "no dan_timeline"
assert dan_render_path.exists() and dan_render_path.stat().st_size > 0, "no render"

instruction = json.loads(instruction_path.read_text(encoding="utf-8"))
timeline_result = json.loads(dan_timeline_path.read_text(encoding="utf-8"))
sequence_result = timeline_result.get("sequence") if isinstance(timeline_result.get("sequence"), dict) else None
assert sequence_result, "dan_timeline has no sequence"
print("sequence tracks:", [(t.get("type"), len(t.get("clips", []))) for t in sequence_result.get("tracks", [])])

# 1) register the finished render as a generated asset + attach as content output
output_asset = P._add_generated_video_asset(
    ROOM, dan_render_path, filename=f"dan_{CONTENT[:8]}_{JOB[:8]}.mp4"
)
P._attach_output_asset(ROOM, CONTENT, JOB, output_asset, dan_render_path, kind="dan_render")
probed = P._probe_video(dan_render_path)
print("registered output asset:", output_asset["id"], probed.get("width"), "x", probed.get("height"))

# 2) write the sequence into the content timeline (what the editor reads)
timeline = dict(instruction.get("timeline") or {})
timeline.update(timeline_result)
timeline["sequence"] = sequence_result
P._update_content(ROOM, CONTENT, {"timeline": timeline})

# 3) mark the job done + content ready
result = {
    "instruction_path": str(instruction_path),
    "dan_timeline_path": str(dan_timeline_path),
    "message": "Dan rendered and registered the finished video.",
    "output_asset_id": output_asset["id"],
    "output_path": str(dan_render_path),
    "output_url": output_asset.get("proxy_url"),
    "render_size": f"{probed.get('width')}x{probed.get('height')}",
    "sequence_created": True,
    "sequence_clip_count": sum(len(t.get("clips") or []) for t in sequence_result.get("tracks", [])),
    "manually_finalized": True,
}
P._update_job(ROOM, JOB, {"status": "done", "result": result, "error": None})
P._update_content(ROOM, CONTENT, {"status": "ready", "timeline": timeline})

# verify
contents = P._read_contents(ROOM)
ct = next(c for c in contents if c["id"] == CONTENT)
jobs = P._read_jobs(ROOM)
jb = next(j for j in jobs if j["id"] == JOB)
caps = [c.get("text", "")[:14] for t in ct["timeline"]["sequence"]["tracks"] if t.get("type") == "caption" for c in t.get("clips", [])]
print("VERIFY job status:", jb.get("status"))
print("VERIFY content status:", ct.get("status"))
print("VERIFY content has sequence:", bool(ct.get("timeline", {}).get("sequence")))
print("VERIFY outputs:", len(ct.get("outputs") or []), "caption count:", len(caps))
print("DONE")
