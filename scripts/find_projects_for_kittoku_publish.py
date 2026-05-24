"""kittoku / publish 用に検索キーワードを広げる。"""
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
    queries = {
        "kittoku-by-kikkawa": "title ILIKE '%吉川%' OR title ILIKE '%キッ%' OR title ILIKE '%KITT%' OR title ILIKE '%kittoku%'",
        "kittoku-by-tokusou": "title ILIKE '%特装%' OR title ILIKE '%HP%' OR title ILIKE '%ホームページ%'",
        "publish-by-domain": "title ILIKE '%ドメイン%' OR title ILIKE '%domain%' OR title ILIKE '%デプロイ%' OR title ILIKE '%vercel%'",
        "publish-by-publish": "title ILIKE '%publish%' OR title ILIKE '%公開%'",
        "b2b-hp": "title ILIKE '%B2B%' OR title ILIKE '%HP%' OR title ILIKE '%サイト%' OR title ILIKE '%LP%'",
    }
    for name, where in queries.items():
        rows = q(token, f"""
            SELECT id AS project_id, title, room_id, created_at
            FROM projects
            WHERE room_id IS NOT NULL AND ({where})
            ORDER BY created_at DESC
            LIMIT 8;
        """)
        print(f"\n=== {name} ===")
        if isinstance(rows, list):
            for r in rows:
                print(f"  project={r['project_id']} room={r['room_id']}")
                print(f"  title_hex={r['title'].encode('utf-8').hex()[:100]}")
        else:
            print(json.dumps(rows, ensure_ascii=False)[:300])


if __name__ == "__main__":
    main()
