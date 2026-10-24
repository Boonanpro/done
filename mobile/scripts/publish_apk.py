"""Publish a built APK so every phone with the app can update itself (2026-10-24).

The app checks GET /api/v1/push/native/app-latest on start and when it comes back to the front, and shows
「新しい版 1.0.x があります［更新する］」 when this APK's versionCode is newer than its own. The owner's phones also get
a notification; tapping it opens the app on that button (mobile/app-update.tsx).

Before anything is placed, the APK is checked (app/services/app_release.problems): it is the Done app, it talks to
the production server (assets/app.config apiBaseUrl), it is signed with the usual key (apksigner certificate SHA-256)
and its versionCode is larger than the one published now. If any check fails, nothing is placed and nobody is told.

Run after building (from the folder whose server the phones talk to, i.e. the live tree):
  python mobile/scripts/publish_apk.py mobile/android/app/build/outputs/apk/release/app-release.apk --notes "作業中の1行を細かくした"
  --dry-run   only check the APK and show what would be recorded; nothing is placed, no notification
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("apk", type=Path)
    ap.add_argument("--notes", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--user", default=None, help="owner user id (default: app.services.owner)")
    args = ap.parse_args()
    if not args.apk.is_file():
        raise SystemExit(f"no such APK: {args.apk}")
    from app.services import app_release
    try:
        record = app_release.publish(args.apk, args.notes, dry_run=args.dry_run)
    except ValueError as e:
        raise SystemExit(str(e))
    result = {"dry_run": args.dry_run, "record": record}
    if not args.dry_run:
        result["push"] = asyncio.run(app_release.notify_owner(record, args.user))
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
