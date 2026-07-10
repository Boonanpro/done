"""Resident SAM 3 blur-mask worker: keeps the model on the GPU between bakes so a job
starts in ~0s instead of paying the ~24s model load every time.

Runs in venv_sam3 (Python 3.13) as a STANDALONE daemon on 127.0.0.1:8876 — deliberately
independent of the app sandbox so `sandbox/restart` (constant during development) does not
drop the model. The sandbox spawns it detached on first use and falls back to the classic
one-shot subprocess if the worker cannot be reached or started.

API (JSON):
  GET  /health          -> {ok, engine, busy, queue, idle_s}
  POST /bake   {job}    -> runs blur_mask_bake.bake() with the cached models; the request
                           BLOCKS until the bake finishes (the caller already runs in a
                           worker thread). Files (mask/meta/progress) are written by the
                           bake itself atomically, so a dropped connection loses nothing.
  POST /probe  {job}    -> same, with probe=True (1-frame detection, ~2s when warm)
  POST /unload          -> drop the models (frees VRAM; process stays)
  POST /quit            -> exit

Jobs run strictly one at a time (the GPU is serial anyway); concurrent POSTs queue on an
internal lock. Models auto-unload after IDLE_UNLOAD_S without a job (VRAM is shared with
the editor and the pop-out RVM bakes).

Start manually:  D:/done/venv_sam3/Scripts/python.exe scripts/blur_mask_worker.py
"""
import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blur_mask_bake as B  # noqa: E402

PORT = 8876
IDLE_UNLOAD_S = 15 * 60

_LOCK = threading.Lock()          # one bake at a time
_STATE = {"busy": False, "queue": 0, "last_job_at": time.time(), "jobs_done": 0}


def _job_to_namespace(job: dict) -> argparse.Namespace:
    """Build the same Namespace argparse would: defaults from the parser, overrides from
    the job dict (keys use underscores: keep_ids, progress_file, ...)."""
    ap = B.build_parser()
    a = ap.parse_args([str(job.get("src") or ""), "--out", str(job.get("out") or "")])
    for k, v in job.items():
        k2 = k.replace("-", "_")
        if hasattr(a, k2) and v is not None:
            setattr(a, k2, v)
    return a


def _idle_watch() -> None:
    while True:
        time.sleep(30)
        idle = time.time() - _STATE["last_job_at"]
        if idle > IDLE_UNLOAD_S and not _STATE["busy"] and B._ENGINE_CACHE["obj"] is not None:
            print(f"idle {idle:.0f}s -> unloading models", flush=True)
            with _LOCK:
                B.unload_models()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A003 - quiet default access log
        pass

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._json(200, {
                "ok": True,
                "engine": B._ENGINE_CACHE["kind"],
                "busy": _STATE["busy"],
                "queue": _STATE["queue"],
                "idle_s": round(time.time() - _STATE["last_job_at"], 1),
                "jobs_done": _STATE["jobs_done"],
            })
        else:
            self._json(404, {"ok": False})

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        try:
            job = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            self._json(400, {"ok": False, "error": "bad json"})
            return
        if self.path == "/quit":
            self._json(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if self.path == "/unload":
            with _LOCK:
                B.unload_models()
            self._json(200, {"ok": True})
            return
        if self.path not in ("/bake", "/probe"):
            self._json(404, {"ok": False})
            return
        if self.path == "/probe":
            job["probe"] = True
        _STATE["queue"] += 1
        try:
            with _LOCK:
                _STATE["queue"] -= 1
                _STATE["busy"] = True
                _STATE["last_job_at"] = time.time()
                t0 = time.time()
                try:
                    a = _job_to_namespace(job)
                    rc = B.bake(a)
                    _STATE["jobs_done"] += 1
                    self._json(200, {"ok": rc == 0, "rc": rc, "wall_s": round(time.time() - t0, 1)})
                except BrokenPipeError:
                    # the caller vanished (sandbox restart) AFTER a successful bake — the
                    # files are already published; never poison the progress file
                    raise
                except Exception as exc:  # noqa: BLE001
                    import traceback
                    traceback.print_exc()
                    # mirror the one-shot script's error contract: poison the progress
                    # file so the server/status endpoint surfaces the failure
                    pf = str(job.get("progress_file") or job.get("progress-file") or "")
                    if pf:
                        try:
                            Path(pf).write_text(
                                json.dumps({"stage": "error", "progress": 0, "error": str(exc)}),
                                encoding="utf-8")
                        except OSError:
                            pass
                    self._json(500, {"ok": False, "error": str(exc)})
                finally:
                    _STATE["busy"] = False
                    _STATE["last_job_at"] = time.time()
        except BrokenPipeError:
            pass  # caller vanished (e.g. sandbox restart) — the bake already published


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--log", default=str(Path(__file__).resolve().parent.parent / "logs" / "blur_worker.log"))
    args = ap.parse_args()
    # the worker owns its log (it is spawned via `cmd /c start` with no inherited pipes —
    # a sandbox-held handle would die with the sandbox; taskkill /T killed child workers)
    try:
        Path(args.log).parent.mkdir(parents=True, exist_ok=True)
        logf = open(args.log, "a", encoding="utf-8", errors="replace", buffering=1)
        sys.stdout = logf
        sys.stderr = logf
    except OSError:
        pass
    threading.Thread(target=_idle_watch, daemon=True, name="idle-watch").start()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"blur worker listening on 127.0.0.1:{args.port}", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
