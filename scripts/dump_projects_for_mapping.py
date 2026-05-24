"""project と room_id の対応を出す。手動マッピング用。"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests
from scripts.apply_migration_057 import get_access_token

PROJECT_REF = "omcnusihkpfyvzglttop"


def q(token: str, sql: str) -> dict:
    res = requests.post(
        f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": sql},
        timeout=60,
    )
    return res.json()


def main():
    token = get_access_token()
    # projects とその room_id 一覧（最新順）
    rows = q(token, """
        SELECT p.id AS project_id, p.title, p.room_id, p.created_at, p.user_id
        FROM projects p
        WHERE p.room_id IS NOT NULL
        ORDER BY p.created_at DESC
        LIMIT 50;
    """)
    print(json.dumps(rows, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
