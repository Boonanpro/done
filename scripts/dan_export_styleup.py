import sys, json, uuid, time, traceback
sys.path.insert(0, "D:/done")
from pathlib import Path
from app.api import production_asset_routes as m

ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
CONTENT = "6b0ba0dc-caa1-4037-bf02-905dcfdb3159"
LOG = Path("D:/done/scripts/dan_export_styleup.log")

def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

try:
    LOG.write_text("", encoding="utf-8")
    contents = m._read_contents(ROOM)
    content = next((c for c in contents if c.get("id") == CONTENT), None)
    if not content:
        log("CONTENT NOT FOUND"); sys.exit(1)
    timeline = content.get("timeline") or {}
    seq = timeline.get("sequence") or {}
    tracks = seq.get("tracks") or []
    nclips = sum(len(t.get("clips") or []) for t in tracks)
    log(f"content={CONTENT} tracks={len(tracks)} clips={nclips} fmt={timeline.get('format') or seq.get('format')}")

    job_id = str(uuid.uuid4())
    job_dir = m._room_dir(ROOM) / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    instruction = {"mode": "export", "timeline": timeline}
    log(f"render start job_id={job_id}")
    t0 = time.time()
    res = m._render_sequence_job(ROOM, job_id, CONTENT, instruction, job_dir)
    log(f"render done in {time.time()-t0:.1f}s")
    log("RESULT=" + json.dumps(res, ensure_ascii=False))
    if res and res.get("output_path"):
        log("OUTPUT=" + res["output_path"])
except Exception as e:
    log("ERROR: " + repr(e))
    tb = traceback.format_exc()
    log(tb[-2000:])
    # if ffmpeg CalledProcessError, dump stderr
    err = getattr(e, "stderr", None)
    if err:
        log("FFMPEG_STDERR_TAIL=" + str(err)[-2000:])
    sys.exit(1)
