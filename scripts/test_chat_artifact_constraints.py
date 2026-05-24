"""057 マイグレーション後の DB 制約を検証する。"""
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
    try:
        return {"status": res.status_code, "body": res.json()}
    except Exception:
        return {"status": res.status_code, "text": res.text}


def main():
    token = get_access_token()

    # 既存の chat_rooms から有効な room_id を1つ取る
    rooms = q(token, "SELECT id FROM chat_rooms ORDER BY created_at DESC LIMIT 1;")
    print("既存 room:", json.dumps(rooms, ensure_ascii=False)[:200])
    if not rooms.get("body"):
        print("no rooms — skip")
        return
    room_id = rooms["body"][0]["id"]

    # テスト1: room_id なしで INSERT → NOT NULL 違反になるはず
    print("\n--- test1: room_id なし INSERT ---")
    r = q(token, """
        INSERT INTO chat_artifact (slug, kind, preview_url, publish_status, artifact_type, delivery_checklist)
        VALUES ('test-no-room', 'production', '/artifacts/test-no-room', 'preview_live', 'tool', '{}'::jsonb);
    """)
    print(json.dumps(r, ensure_ascii=False)[:300])

    # テスト2: room_id 付き INSERT → 成功
    print("\n--- test2: 同じ (room_id, slug) を2回 INSERT ---")
    sql_ins = f"""
        INSERT INTO chat_artifact (room_id, slug, kind, preview_url, publish_status, artifact_type, delivery_checklist)
        VALUES ('{room_id}', 'test-dup', 'production', '/artifacts/test-dup', 'preview_live', 'tool', '{{}}'::jsonb);
    """
    r1 = q(token, sql_ins)
    print("1回目:", json.dumps(r1, ensure_ascii=False)[:200])
    r2 = q(token, sql_ins)
    print("2回目:", json.dumps(r2, ensure_ascii=False)[:300])

    # クリーンアップ
    q(token, f"DELETE FROM chat_artifact WHERE slug = 'test-dup' AND room_id = '{room_id}';")
    print("\n(cleanup OK)")


if __name__ == "__main__":
    main()
