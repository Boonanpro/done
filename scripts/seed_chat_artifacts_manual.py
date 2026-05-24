"""手動マッピングで chat_artifact を 4 件登録する。"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests
from scripts.apply_migration_057 import get_access_token

PROJECT_REF = "omcnusihkpfyvzglttop"

OWNER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"

# (slug, room_id, project_id, label, artifact_type)
ROWS = [
    (
        "aix-dashboard",
        "31d77dd4-9b95-4716-b17b-0578314f34ba",
        "4430eda7-cc40-4469-a6a6-11adcd138ab1",
        "AIX Dashboard",
        "dashboard",
    ),
    (
        "inspection-report",
        "60760f4c-e236-49f4-a72c-c556bc56fa68",
        "3a7fb3e5-8fe8-4f81-9b70-d6ef653d49fb",
        "Inspection Report",
        "tool",
    ),
    (
        "salonboard-styleup",
        "bd05fcc0-c143-4d1c-828e-7624e087b6c1",
        "6a1935dd-efa8-4726-bf5d-128d87e4ce07",
        "Salonboard StyleUp",
        "tool",
    ),
    (
        "test-edit",
        "821deffe-4558-47c9-9b89-ec422ff73e20",
        "74eb2a2e-5027-4828-af2d-58ebb32f51af",
        "Test Edit",
        "tool",
    ),
]


def q(token: str, sql: str) -> dict:
    res = requests.post(
        f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": sql},
        timeout=60,
    )
    return {"status": res.status_code, "body": res.json() if res.headers.get("content-type", "").startswith("application/json") else res.text}


def main():
    token = get_access_token()
    for slug, room_id, project_id, label, atype in ROWS:
        # quoting で SQL injection を防ぐため固定値だけ使う
        sql = f"""
            INSERT INTO chat_artifact
                (room_id, project_id, slug, kind, artifact_type, label, preview_url,
                 share_url, draft_url, publish_status, created_by, delivery_status,
                 delivery_mode, target_audience, requires_auth, payment_responsibility,
                 delivery_checklist)
            VALUES
                ('{room_id}', '{project_id}', '{slug}', 'production', '{atype}',
                 '{label}', '/artifacts/{slug}',
                 '/preview/{slug}', '/preview/{slug}', 'preview_live', '{OWNER_ID}',
                 'preview', 'preview', 'internal', false, 'owner_pays', '{{}}'::jsonb)
            ON CONFLICT (room_id, slug) DO NOTHING
            RETURNING id;
        """
        r = q(token, sql)
        print(f"{slug}: {json.dumps(r, ensure_ascii=False)[:200]}")

    print("\n=== 結果確認 ===")
    rows = q(token, "SELECT room_id, slug, label FROM chat_artifact ORDER BY created_at DESC;")
    print(json.dumps(rows, ensure_ascii=False))


if __name__ == "__main__":
    main()
