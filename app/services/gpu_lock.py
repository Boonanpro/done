"""Single-GPU job serialization.

Two GPU jobs launched together (Qwen3-TTS + SAM3 mask bake, 2026-09-04) both stalled
for 88 minutes instead of finishing in 1 + 4. Every GPU-heavy subprocess (voice
synthesis, mask baking, local video models) takes this lock first, so jobs queue
instead of thrashing VRAM. Cross-process, dependency-free: a lock FILE created with
O_EXCL; a holder that died leaves a stale file which is broken after `stale_s`.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

LOCK_PATH = Path(__file__).resolve().parents[2] / "uploads" / ".gpu.lock"


class GpuLock:
    def __init__(self, label: str = "", timeout: float = 3600.0, stale_s: float = 2400.0,
                 path: Path | None = None):
        self.path = path or LOCK_PATH
        self.label = label
        self.timeout = timeout
        self.stale_s = stale_s
        self._fd: int | None = None
        self.waited = 0.0

    def __enter__(self) -> "GpuLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.timeout
        t0 = time.time()
        while True:
            try:
                self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, f"{os.getpid()} {self.label} {time.time():.0f}".encode())
                self.waited = time.time() - t0
                return self
            except FileExistsError:
                try:
                    # A long-running live job must never lose its lock just because
                    # synthesis took longer than expected. Recover a dead owner now.
                    import psutil
                    age = time.time() - self.path.stat().st_mtime
                    owner = self.path.read_text().split()
                    dead = bool(owner and owner[0].isdigit() and not psutil.pid_exists(int(owner[0])))
                    malformed = not owner or not owner[0].isdigit()
                    if dead or (malformed and age > self.stale_s):
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.time() > deadline:
                    raise TimeoutError(f"GPU lock timeout ({self.timeout:.0f}s): {self.path}")
                time.sleep(1.0)

    def __exit__(self, *exc) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def holder() -> str | None:
    """Who holds the GPU right now (label text) or None."""
    try:
        return LOCK_PATH.read_text(encoding="utf-8", errors="ignore").strip() or "?"
    except OSError:
        return None
