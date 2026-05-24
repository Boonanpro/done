"""artifact slug ごとに対応する project (= room_id) を探す。"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests
from scripts.apply_migration_057 import get_access_token

PROJECT_REF = "omcnusihkpfyvzglttop"

# ディスクに存在する artifact (production)
ARTIFACTS = [
    ("aix-dashboard", ["aix", "AIX", "ダッシュボード", "dashboard"]),
    ("inspection-report", ["inspection", "点検", "車検", "報告"]),
    ("kittoku", ["kittoku", "吉川", "特装", "キット", "kikkawa"]),
    ("publish", ["publish", "公開", "ドメイン"]),
    ("salonboard-styleup", ["salon", "サロン", "styleup", "スタイル"]),
    ("test-edit", ["test-edit", "テスト"]),
]


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
    out = {}
    for slug, keywords in ARTIFACTS:
        clauses = " OR ".join([f"title ILIKE '%{k}%'" for k in keywords])
        rows = q(token, f"""
            SELECT id AS project_id, title, room_id, user_id, created_at
            FROM projects
            WHERE room_id IS NOT NULL AND ({clauses})
            ORDER BY created_at DESC
            LIMIT 5;
        """)
        out[slug] = rows
        print(f"\n=== {slug} ===")
        if isinstance(rows, list):
            for r in rows:
                # title を hex 表示で文字化け回避（UUID と room_id だけ大事）
                print(f"  project_id={r['project_id']}")
                print(f"  room_id   ={r['room_id']}")
                print(f"  user_id   ={r['user_id']}")
                print(f"  title_hex ={r['title'].encode('utf-8').hex()[:80]}...")
                print()
        else:
            print(json.dumps(rows, ensure_ascii=False)[:300])


if __name__ == "__main__":
    main()
