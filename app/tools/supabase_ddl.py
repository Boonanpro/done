"""
Supabase DDL migration applier via Management API.

SUPABASE_ACCESS_TOKEN (Personal Access Token) を使って DDL を実行する。
ブラウザ自動化なしで動作する。

PAT は https://supabase.com/dashboard/account/tokens で発行し、
.env に SUPABASE_ACCESS_TOKEN=sbp_... として保存する。
"""
from __future__ import annotations

import logging
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent


class SupabaseDDLError(RuntimeError):
    pass


def apply_sql(sql: str) -> dict:
    """任意の SQL を Management API 経由で適用する。

    DDL (CREATE TABLE / ALTER TABLE / etc) も動く。
    """
    token = settings.SUPABASE_ACCESS_TOKEN
    if not token:
        raise SupabaseDDLError(
            "SUPABASE_ACCESS_TOKEN が .env に未設定。\n"
            "https://supabase.com/dashboard/account/tokens で PAT を発行し、\n"
            ".env に SUPABASE_ACCESS_TOKEN=sbp_... を追加してください。"
        )
    ref = settings.SUPABASE_PROJECT_REF
    url = f"https://api.supabase.com/v1/projects/{ref}/database/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    res = httpx.post(url, headers=headers, json={"query": sql}, timeout=120)
    if res.status_code >= 400:
        raise SupabaseDDLError(
            f"Supabase Management API エラー HTTP {res.status_code}: {res.text[:500]}"
        )
    try:
        return res.json()
    except Exception:
        return {"text": res.text}


def apply_migration(filename: str) -> dict:
    """`supabase/migrations/<filename>` を読み込んで適用する。"""
    path = PROJECT_ROOT / "supabase" / "migrations" / filename
    if not path.exists():
        raise SupabaseDDLError(f"{path} が存在しません")
    sql = path.read_text(encoding="utf-8")
    logger.info("Applying migration %s (%d bytes)", filename, len(sql))
    return apply_sql(sql)


if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) < 2:
        print("Usage: python -m app.tools.supabase_ddl <migration-filename>")
        sys.exit(1)
    try:
        result = apply_migration(sys.argv[1])
        print(json.dumps(result, indent=2, ensure_ascii=False)[:2000])
    except SupabaseDDLError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
