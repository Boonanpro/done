"""Generate deterministic PNG icons for artifact PWA manifests."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.artifact_public_assets import ensure_artifact_icons  # noqa: E402


def main() -> int:
    slugs = sys.argv[1:]
    if not slugs:
        artifacts_dir = PROJECT_ROOT / "frontend" / "src" / "app" / "artifacts"
        slugs = [
            p.name
            for p in sorted(artifacts_dir.iterdir())
            if p.is_dir() and not p.name.startswith("_") and p.name != "publish" and (p / "page.tsx").exists()
        ]

    for slug in slugs:
        icons = ensure_artifact_icons(slug, slug.replace("-", " "))
        if icons:
            print(f"{slug}: {icons}")
        else:
            print(f"{slug}: skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
