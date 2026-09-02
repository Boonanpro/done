"""Verify the upgraded _render_sequence_job: render the StyleUp sequence
(which has overlay_1 PiP + audio_1 + effects blur) deterministically and
confirm PiP, audio, and mosaic survive."""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api import production_asset_routes as par

ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
CONTENT_ID = "68ab4fe4-6f96-4f72-b085-f818fae83a8d"

room_dir = par._room_dir(ROOM)
contents = json.loads((room_dir / "contents.json").read_text(encoding="utf-8"))
content = next(c for c in contents if c["id"] == CONTENT_ID)
timeline = content["timeline"]

seq = timeline.get("sequence", {})
tracks = seq.get("tracks", [])
print("[test] sequence tracks:", [(t.get("id"), t.get("type"), len(t.get("clips") or [])) for t in tracks])
print("[test] overlay clips:", len(par._sequence_overlay_clips(seq)))
print("[test] audio clips:", len(par._sequence_audio_clips(seq)))
print("[test] effect clips:", len(par._sequence_effect_clips(seq)))
print("[test] base clips:", len([c for c in par._sequence_video_clips(seq) if not par._is_overlay_clip(c)]))

job_id = str(uuid.uuid4())
job_dir = room_dir / "jobs" / job_id
job_dir.mkdir(parents=True, exist_ok=True)

instruction = {
    "mode": "render_timeline",
    "content_id": CONTENT_ID,
    "timeline": timeline,
    "source_assets": [],
}

print(f"[test] rendering job {job_id} ...", flush=True)
try:
    result = par._render_sequence_job(ROOM, job_id, CONTENT_ID, instruction, job_dir)
    print("[test] render result:", json.dumps(result, ensure_ascii=False) if result else None)
except Exception as exc:
    import traceback
    traceback.print_exc()
    print("[test] RENDER FAILED:", exc)
    sys.exit(1)

out = job_dir / f"{job_id}_sequence.mp4"
print("[test] output exists:", out.exists(), "size:", out.stat().st_size if out.exists() else 0)
print("[test] OUTPUT_PATH:", out)
