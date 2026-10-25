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
import re
import shutil
import subprocess
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
RELEASE_FILE = Path(os.getenv("DAN_APP_RELEASE_FILE") or (_ROOT / ".data" / "app_release.json"))
UPLOADS = _ROOT / "uploads"
# Which version each phone runs (2026-10-25: Dan could not tell whether the owner's phone had installed 1.0.76; the app
# now sends its version with every app-latest question). {"<user_id>|<device>": {version_name, version_code, device, seen_at}}
INSTALLS_FILE = Path(os.getenv("DAN_APP_INSTALLS_FILE") or (_ROOT / ".data" / "app_installs.json"))

# 登録してよい APK の条件（2026-10-24 見直し: 試験用の接続先を向いた APK や署名違いも登録できていた）。
# 接続先は APK の中の assets/app.config（expo の extra.apiBaseUrl）、署名は apksigner の証明書の SHA-256。
PACKAGE = "app.done.dan"
PRODUCTION_API_BASE = "https://dan.paina.info"
# 従来の鍵（Windows で作った版から同じ。android/app/debug.keystore）。鍵を替える時はここを替える
SIGNER_SHA256 = "fac61745dc0903786fb9ede62a962b399f7348f0bb6f899b8332667591033b9c"


def _build_tool(name: str) -> str:
    sdk = os.getenv("ANDROID_HOME") or "/opt/homebrew/share/android-commandlinetools"
    tools = sorted((Path(sdk) / "build-tools").glob(f"*/{name}"))
    if not tools:
        raise RuntimeError(f"{name} not found under {sdk}/build-tools")
    return str(tools[-1])


def apk_facts(apk: Path) -> dict[str, Any]:
    """What is inside the APK: package, version_name, version_code, api_base, signers (SHA-256 of each certificate)."""
    badging = subprocess.run([_build_tool("aapt"), "dump", "badging", str(apk)], capture_output=True, text=True, check=True).stdout
    m = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging)
    api_base = None
    try:
        with zipfile.ZipFile(apk) as z:
            api_base = (json.loads(z.read("assets/app.config")).get("extra") or {}).get("apiBaseUrl")
    except (KeyError, ValueError, zipfile.BadZipFile):
        api_base = None
    env = dict(os.environ)
    env.setdefault("JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home")
    certs = subprocess.run([_build_tool("apksigner"), "verify", "--print-certs", str(apk)], capture_output=True, text=True, env=env)
    signers = re.findall(r"certificate SHA-256 digest: ([0-9a-f]{64})", certs.stdout)
    return {
        "package": m.group(1) if m else None,
        "version_code": int(m.group(2)) if m else None,
        "version_name": m.group(3) if m else None,
        "api_base": api_base,
        "signers": signers if certs.returncode == 0 else [],
    }


def problems(facts: dict[str, Any], current: Optional[dict[str, Any]]) -> list[str]:
    """Why this APK must not be registered as the newest version (empty = it may)."""
    out = []
    if facts.get("package") != PACKAGE:
        out.append(f"Done のアプリではない（{facts.get('package')}）")
    base = (facts.get("api_base") or "").rstrip("/")
    if base != PRODUCTION_API_BASE:
        out.append(f"接続先が本番ではない（{facts.get('api_base') or '読めない'}）")
    if facts.get("signers") != [SIGNER_SHA256]:
        out.append(f"署名が従来の鍵と違う（{', '.join(facts.get('signers') or []) or '確かめられない'}）")
    code = facts.get("version_code")
    if not isinstance(code, int) or code <= 0:
        out.append("versionCode が読めない")
    elif current and code <= int(current.get("version_code") or 0):
        out.append(f"versionCode {code} が今の最新（{current.get('version_name')} / {current.get('version_code')}）より大きくない")
    return out


def latest() -> Optional[dict[str, Any]]:
    """The newest published APK: version_name, version_code, url, size, notes, published_at. None when none yet."""
    try:
        data = json.loads(RELEASE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("url") or not isinstance(data.get("version_code"), int):
        return None
    return {k: data.get(k) for k in ("version_name", "version_code", "url", "size", "notes", "published_at")}


def note_installed(user_id: str, version_name: str, version_code: Any, device: str = "") -> None:
    """Remember the version a phone said it runs (GET app-latest with ?v=&code=&device=). Best effort."""
    try:
        code = int(version_code)
    except (TypeError, ValueError):
        return
    name = str(version_name or "")[:20]
    dev = " ".join(str(device or "").split())[:60]
    if not name or code <= 0:
        return
    key = f"{user_id or 'anonymous'}|{dev}"
    try:
        data = json.loads(INSTALLS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data[key] = {"user_id": user_id or None, "device": dev, "version_name": name, "version_code": code,
                 "seen_at": datetime.now(timezone.utc).isoformat()}
    try:
        INSTALLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = INSTALLS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(INSTALLS_FILE)
    except OSError:
        pass


def installed(user_id: Optional[str] = None) -> list[dict[str, Any]]:
    """The versions phones last said they run (newest first); only this user's when user_id is given."""
    try:
        data = json.loads(INSTALLS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = [v for v in (data.values() if isinstance(data, dict) else []) if isinstance(v, dict)]
    if user_id:
        rows = [r for r in rows if r.get("user_id") == user_id]
    return sorted(rows, key=lambda r: str(r.get("seen_at") or ""), reverse=True)


def publish(apk: Path, notes: str = "", dry_run: bool = False) -> dict[str, Any]:
    """Check the APK (problems) and, unless dry_run, copy it into uploads under a fresh name and record it as the
    newest version. Raises ValueError with every problem when it must not be registered; nothing is placed then."""
    facts = apk_facts(apk)
    found = problems(facts, latest())
    if found:
        raise ValueError("登録しない: " + " / ".join(found))
    record = {
        "version_name": facts["version_name"],
        "version_code": int(facts["version_code"]),
        "url": None,
        "size": apk.stat().st_size,
        "notes": notes.strip()[:200],
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
    if dry_run:
        return record
    UPLOADS.mkdir(parents=True, exist_ok=True)
    name = f"Done-{record['version_name']}-{uuid.uuid4().hex[:8]}.apk"
    shutil.copyfile(apk, UPLOADS / name)
    record["url"] = f"/api/v1/files/{name}"
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
