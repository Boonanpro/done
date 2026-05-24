"""057 マイグレーション適用後の検証。"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests
from scripts.apply_migration_057 import get_access_token

PROJECT_REF = "omcnusihkpfyvzglttop"


def query(token: str, sql: str) -> dict:
    url = f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query"
    res = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": sql},
        timeout=60,
    )
    return res.json()


def main():
    token = get_access_token()

    print("\n=== chat_artifact カラム一覧 ===")
    cols = query(
        token,
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'chat_artifact'
        ORDER BY ordinal_position;
        """,
    )
    print(json.dumps(cols, indent=2, ensure_ascii=False))

    print("\n=== 既存行数 ===")
    cnt = query(token, "SELECT COUNT(*) AS n FROM chat_artifact;")
    print(json.dumps(cnt, ensure_ascii=False))

    print("\n=== room_id 別件数 (top 10) ===")
    g = query(
        token,
        "SELECT room_id, COUNT(*) AS n FROM chat_artifact GROUP BY room_id ORDER BY n DESC LIMIT 10;",
    )
    print(json.dumps(g, ensure_ascii=False))

    print("\n=== インデックス一覧 ===")
    idx = query(
        token,
        """
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'chat_artifact'
        ORDER BY indexname;
        """,
    )
    print(json.dumps(idx, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
