"""Deploy frontend and point artifact delivery aliases at the new deployment.

Usage:
    python scripts/deploy_frontend_artifacts.py
    python scripts/deploy_frontend_artifacts.py salonboard-styleup kittoku

The Vercel deployment URL (frontend-*.vercel.app) is an internal build target.
Client-facing artifact URLs are always https://<slug>-done.vercel.app/.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = ROOT / "frontend" / "src" / "app" / "artifacts"
DEPLOYMENT_RE = re.compile(r"https://frontend-[^\s]+\.vercel\.app")
VERCEL = shutil.which("vercel") or shutil.which("vercel.cmd") or "vercel"


def artifact_slugs() -> list[str]:
    slugs: list[str] = []
    for path in sorted(ARTIFACTS_DIR.iterdir()):
        if path.name.startswith("_") or path.name == "publish":
            continue
        if (path / "page.tsx").exists():
            slugs.append(path.name)
    return slugs


def run(cmd: list[str]) -> str:
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    sys.stdout.buffer.write(proc.stdout.encode("utf-8", errors="replace"))
    if proc.stdout and not proc.stdout.endswith("\n"):
        sys.stdout.buffer.write(b"\n")
    return proc.stdout


def main() -> int:
    slugs = sys.argv[1:] or artifact_slugs()
    if not slugs:
        print("No artifact slugs found.", file=sys.stderr)
        return 1

    out = run([VERCEL, "deploy", "--prod", "--yes"])
    matches = DEPLOYMENT_RE.findall(out)
    if not matches:
        print("Could not find Vercel deployment URL in output.", file=sys.stderr)
        return 1
    deployment = matches[-1]

    for slug in slugs:
        alias = f"{slug}-done.vercel.app"
        run([VERCEL, "alias", "set", deployment, alias])
        print(f"[artifact-alias] https://{alias} -> {deployment}")

    print("\nClient-facing URLs:")
    for slug in slugs:
        print(f"  https://{slug}-done.vercel.app/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
