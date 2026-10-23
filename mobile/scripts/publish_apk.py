"""Publish a built APK so every phone with the app can update itself (2026-10-24).

The app checks GET /api/v1/push/native/app-latest on start and when it comes back to the front, and shows
「新しい版 1.0.x があります［更新する］」 when this APK's versionCode is newer than its own. The owner's phones also get
a notification; tapping it opens the app on that button (mobile/app-update.tsx).

Run after building (from the folder whose server the phones talk to, i.e. the live tree):
  python mobile/scripts/publish_apk.py mobile/android/app/build/outputs/apk/release/app-release.apk --notes "作業中の1行を細かくした"
  --no-push   record it without sending the notification
The version is read from the APK itself (aapt), so the record always matches the file.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _aapt() -> str:
    sdk = os.getenv("ANDROID_HOME") or "/opt/homebrew/share/android-commandlinetools"
    tools = sorted((Path(sdk) / "build-tools").glob("*/aapt"))
    if not tools:
        raise SystemExit(f"aapt not found under {sdk}/build-tools")
    return str(tools[-1])


def apk_version(apk: Path) -> tuple[str, int, str]:
    out = subprocess.run([_aapt(), "dump", "badging", str(apk)], capture_output=True, text=True, check=True).stdout
    m = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", out)
    if not m:
        raise SystemExit("could not read the version from the APK")
    return m.group(3), int(m.group(2)), m.group(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("apk", type=Path)
    ap.add_argument("--notes", default="")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--user", default=None, help="owner user id (default: app.services.owner)")
    args = ap.parse_args()
    if not args.apk.is_file():
        raise SystemExit(f"no such APK: {args.apk}")
    name, code, package = apk_version(args.apk)
    if package != "app.done.dan":
        raise SystemExit(f"not the Done app: {package}")
    from app.services import app_release
    record = app_release.publish(args.apk, name, code, args.notes)
    result = {"published": record}
    if not args.no_push:
        result["push"] = asyncio.run(app_release.notify_owner(record, args.user))
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
