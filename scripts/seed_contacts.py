import sys
sys.path.insert(0, "D:/done")

from app.services.supabase_client import get_supabase_client


def seed():
    sb = get_supabase_client().client

    users = sb.table("users").select("id").limit(1).execute()
    if not users.data:
        print("ユーザーが見つかりません")
        return
    user_id = users.data[0]["id"]

    samples = [
        {"name": "田中太郎", "company": "株式会社サンプル", "email": "tanaka@example.com", "phone": "090-1234-5678", "memo": "Web制作案件の担当者", "created_by": user_id},
        {"name": "鈴木花子", "company": "デザインラボ合同会社", "email": "suzuki@designlab.example.com", "phone": "080-9876-5432", "created_by": user_id},
        {"name": "山田一郎", "email": "yamada@example.com", "memo": "フリーランスのエンジニア", "created_by": user_id},
    ]

    for sample in samples:
        result = sb.table("contacts").insert(sample).execute()
        if result.data:
            print(f"  作成: {result.data[0]['name']} ({result.data[0]['id']})")
        else:
            print(f"  失敗: {sample['name']}")

    print(f"サンプルデータ {len(samples)} 件を投入しました")


if __name__ == "__main__":
    seed()
