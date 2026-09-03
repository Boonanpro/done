"""Apply a Supabase migration via Management API.

Usage:
    python scripts/apply_migration.py 044_inquiry.sql
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests
from playwright.sync_api import sync_playwright

from app.config import settings

PROJECT_REF = "omcnusihkpfyvzglttop"
USER_DATA_DIR = PROJECT_ROOT / ".playwright-supabase"


def get_access_token() -> str:
    # A management PAT is the durable, non-interactive credential for schema
    # changes.  Browser cookies are only a fallback for older workspaces.
    if settings.SUPABASE_ACCESS_TOKEN:
        return settings.SUPABASE_ACCESS_TOKEN
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=True,
        )
        page = ctx.new_page()
        page.goto(
            f"https://supabase.com/dashboard/project/{PROJECT_REF}",
            wait_until="domcontentloaded",
        )
        page.wait_for_timeout(3000)

        if "/sign-in" in page.url:
            print("[ERROR] 未ログイン。ブラウザ用 persistent context が未認証。")
            ctx.close()
            sys.exit(1)

        all_storage = page.evaluate(
            "() => Object.fromEntries(Object.keys(localStorage).map(k => [k, localStorage.getItem(k)]))"
        )
        token = None
        for k, v in all_storage.items():
            if not v:
                continue
            if "access_token" in v:
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, dict) and parsed.get("access_token"):
                        token = parsed["access_token"]
                        break
                    if isinstance(parsed, list):
                        for item in parsed:
                            if isinstance(item, dict) and item.get("access_token"):
                                token = item["access_token"]
                                break
                        if token:
                            break
                except json.JSONDecodeError:
                    continue
            if k.startswith("sb-") and "auth-token" in k:
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, dict) and parsed.get("access_token"):
                        token = parsed["access_token"]
                        break
                except json.JSONDecodeError:
                    pass

        ctx.close()
        if not token:
            raise RuntimeError("access_token を取得できませんでした")
        return token


def apply_sql(token: str, sql: str) -> dict:
    url = f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    res = requests.post(url, headers=headers, json={"query": sql}, timeout=120)
    print(f"[INFO] HTTP {res.status_code}")
    try:
        return res.json()
    except Exception:
        return {"text": res.text}


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/apply_migration.py <filename>")
        sys.exit(1)
    filename = sys.argv[1]
    path = PROJECT_ROOT / "supabase" / "migrations" / filename
    if not path.exists():
        print(f"[ERROR] {path} not found")
        sys.exit(1)

    sql = path.read_text(encoding="utf-8")
    print(f"[INFO] {path.name} ({len(sql)} bytes)")

    print("[INFO] Getting access token...")
    token = get_access_token()
    print(f"[INFO] token: {token[:20]}...")

    print(f"\n[STEP] Applying {filename}")
    r = apply_sql(token, sql)
    print(json.dumps(r, indent=2, ensure_ascii=False)[:2000])


if __name__ == "__main__":
    main()
