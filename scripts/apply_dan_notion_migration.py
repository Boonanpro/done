"""Supabase Management API 経由で 036_dan_notion.sql を適用する。

手順:
  1. Playwright persistent context (.playwright-supabase) で Supabase Dashboard を開く
  2. localStorage からアクセストークン (sb-supabase-auth-token 等) を取得
  3. https://api.supabase.com/v1/projects/{ref}/database/query に SQL を POST
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests
from playwright.sync_api import sync_playwright
PROJECT_REF = "omcnusihkpfyvzglttop"
MIGRATION_FILE = PROJECT_ROOT / "supabase" / "migrations" / "036_dan_notion.sql"
USER_DATA_DIR = PROJECT_ROOT / ".playwright-supabase"


def _get_github_credentials() -> tuple[str, str] | None:
    try:
        import json as _json
        from app.services.supabase_client import get_supabase_client
        from app.services.encryption import get_encryption_service
        sb = get_supabase_client().client
        enc = get_encryption_service()
        res = sb.table("credentials").select("*").eq("service_name", "github").limit(1).execute()
        if not res.data:
            return None
        d = _json.loads(enc.decrypt(res.data[0]["encrypted_data"]))
        return d["id"], d["password"]
    except Exception as e:
        print(f"[WARN] credentials取得失敗: {e}")
        return None


def get_access_token() -> str:
    """Persistent context で Supabase に行き、localStorage から access_token を取り出す"""
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            slow_mo=200,
        )
        page = ctx.new_page()
        page.goto(f"https://supabase.com/dashboard/project/{PROJECT_REF}", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        if "/sign-in" in page.url:
            print("[INFO] サインイン画面。GitHub OAuth ボタンをクリック")
            try:
                page.get_by_role("button", name="Continue with GitHub").click(timeout=10_000)
            except Exception:
                try:
                    page.locator("text=Continue with GitHub").first.click(timeout=10_000)
                except Exception as e:
                    print(f"[WARN] GitHub ボタン押下失敗: {e}")
            page.wait_for_timeout(4000)

            # GitHub ログインページならクレデンシャル投入
            if "github.com/login" in page.url or "github.com/session" in page.url:
                creds = _get_github_credentials()
                if creds:
                    user, pw = creds
                    print(f"[INFO] GitHub に自動ログイン: {user}")
                    try:
                        page.fill("input[name='login']", user)
                        page.fill("input[name='password']", pw)
                        page.click("input[name='commit']")
                        page.wait_for_timeout(5000)
                    except Exception as e:
                        print(f"[WARN] GitHub 自動入力失敗: {e}")

            # OAuth 認可画面 / 2FA は手動対応
            print("[ACTION] 必要なら 2FA を入力。最大 5 分待機します。")
            try:
                page.wait_for_url(f"**/project/{PROJECT_REF}**", timeout=300_000)
            except Exception:
                print("[ERROR] サインイン完了を検知できませんでした")
                ctx.close()
                raise
            page.wait_for_timeout(3000)

        # localStorage を全件ダンプして探す
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
                        print(f"[INFO] access_token を {k} から取得")
                        break
                    if isinstance(parsed, list):
                        for item in parsed:
                            if isinstance(item, dict) and item.get("access_token"):
                                token = item["access_token"]
                                print(f"[INFO] access_token を {k} (list) から取得")
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
                        print(f"[INFO] access_token を {k} から取得")
                        break
                except json.JSONDecodeError:
                    pass

        if not token:
            print("[DEBUG] localStorage keys:", list(all_storage.keys())[:30])
            ctx.close()
            raise RuntimeError("access_token を localStorage から取得できませんでした")

        ctx.close()
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
    if not MIGRATION_FILE.exists():
        print(f"[ERROR] {MIGRATION_FILE} が見つかりません")
        sys.exit(1)

    sql = MIGRATION_FILE.read_text(encoding="utf-8")
    print(f"[INFO] {MIGRATION_FILE.name} ({len(sql)} bytes)")

    # 旧テーブル DROP (存在すれば)
    drop_sql = """
    DROP TABLE IF EXISTS agent_traces CASCADE;
    DROP TABLE IF EXISTS trigger_runs CASCADE;
    DROP TABLE IF EXISTS triggers CASCADE;
    DROP TABLE IF EXISTS block_embeddings CASCADE;
    DROP TABLE IF EXISTS block_versions CASCADE;
    DROP TABLE IF EXISTS block_files CASCADE;
    DROP TABLE IF EXISTS dan_notifications CASCADE;
    DROP TABLE IF EXISTS blocks CASCADE;
    DROP FUNCTION IF EXISTS update_blocks_updated_at() CASCADE;
    DROP FUNCTION IF EXISTS update_dan_notion_updated_at() CASCADE;
    DROP FUNCTION IF EXISTS save_block_version() CASCADE;
    DROP FUNCTION IF EXISTS search_blocks_by_embedding(uuid, vector, int) CASCADE;
    """

    print("[INFO] アクセストークン取得中...")
    token = get_access_token()
    print(f"[INFO] token: {token[:20]}...")

    print("\n[STEP 1] 旧テーブル DROP")
    r1 = apply_sql(token, drop_sql)
    print(json.dumps(r1, indent=2, ensure_ascii=False)[:500])

    print("\n[STEP 2] 036_dan_notion.sql 適用")
    r2 = apply_sql(token, sql)
    print(json.dumps(r2, indent=2, ensure_ascii=False)[:1500])

    print("\n[DONE]")


if __name__ == "__main__":
    main()
