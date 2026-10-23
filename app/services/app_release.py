"""The phone app's newest APK, for the app's own 「新しい版があります［更新する］」 (2026-10-24).

本人「とりあえずインストールを押すやつで良いわ。いちいちUSB繋いでデバックするよりはまし。ただどこから押せばいいのか
分からないのでそれは分かりやすくしてほしい」. After an APK is built, ``mobile/scripts/publish_apk.py`` copies it to the
uploads folder (served by /api/v1/files/<name>), records it here and sends the owner's phones a notification. The app
reads ``GET /api/v1/push/native/app-latest`` on start and whenever it comes back to the front, shows the button when the recorded
versionCode is newer than its own, downloads the APK and opens Android's install screen (mobile/app-update.tsx).

The record is one JSON file in the repository's .data folder (not in git); the newest publish replaces it.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
RELEASE_FILE = Path(os.getenv("DAN_APP_RELEASE_FILE") or (_ROOT / ".data" / "app_release.json"))
UPLOADS = _ROOT / "uploads"


def latest() -> Optional[dict[str, Any]]:
    """The newest published APK: version_name, version_code, url, size, notes, published_at. None when none yet."""
    try:
        data = json.loads(RELEASE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("url") or not isinstance(data.get("version_code"), int):
        return None
    return {k: data.get(k) for k in ("version_name", "version_code", "url", "size", "notes", "published_at")}


def publish(apk: Path, version_name: str, version_code: int, notes: str = "") -> dict[str, Any]:
    """Copy the APK into uploads under a fresh name and record it as the newest version."""
    if version_code <= 0 or not version_name:
        raise ValueError("version_name and a positive version_code are required")
    current = latest()
    if current and current["version_code"] > version_code:
        raise ValueError(f"a newer version is already published ({current['version_name']} / {current['version_code']})")
    UPLOADS.mkdir(parents=True, exist_ok=True)
    name = f"Done-{version_name}-{uuid.uuid4().hex[:8]}.apk"
    shutil.copyfile(apk, UPLOADS / name)
    record = {
        "version_name": version_name,
        "version_code": int(version_code),
        "url": f"/api/v1/files/{name}",
        "size": (UPLOADS / name).stat().st_size,
        "notes": notes.strip()[:200],
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
    RELEASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = RELEASE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(RELEASE_FILE)
    return record


async def notify_owner(record: dict[str, Any], user_id: Optional[str] = None) -> dict[str, int]:
    """Tell the owner's phones that a new version is there. Tapping opens the app on the update button."""
    from app.services.owner import resolve_owner_user_id
    from app.services.push_service import get_push_service

    owner = user_id or resolve_owner_user_id()
    if not owner:
        return {"attempted": 0, "sent": 0, "failed": 0}
    svc = get_push_service()
    rows = svc.supabase.table("push_subscriptions").select("endpoint").eq("room_id", f"user:{owner}").execute().data or []
    sent = failed = 0
    for endpoint in {r.get("endpoint") for r in rows}:
        if not str(endpoint or "").startswith("ExponentPushToken["):
            continue
        ok = await svc._send_expo_push(
            token=endpoint,
            title="アプリの新しい版があります",
            body=f"Done {record['version_name']}。開いて「更新する」を押してください",
            url="/app-update",
        )
        sent += 1 if ok else 0
        failed += 0 if ok else 1
    return {"attempted": sent + failed, "sent": sent, "failed": failed}
