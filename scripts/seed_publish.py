"""
publish のサンプルデータ投入スクリプト
create_feature で自動生成。中身を実装してください。
完了報告前に必ず実行すること。
"""
import sys
sys.path.insert(0, "D:/done")

from app.services.supabase_client import get_supabase_client


def seed():
    sb = get_supabase_client().client

    # オーナーのuser_idを取得
    users = sb.table("users").select("id").limit(1).execute()
    if not users.data:
        print("ユーザーが見つかりません")
        return
    user_id = users.data[0]["id"]

    # TODO: サンプルデータを定義してください
    samples = [
        # {"title": "サンプル1", "created_by": user_id},
        # {"title": "サンプル2", "created_by": user_id},
    ]

    for sample in samples:
        result = sb.table("publish").insert(sample).execute()
        if result.data:
            print(f"  作成: {result.data[0].get('id', '?')}")
        else:
            print(f"  失敗: {sample}")

    print(f"サンプルデータ {len(samples)} 件を投入しました")


if __name__ == "__main__":
    seed()
