"""
chat_artifact のサンプルデータ投入スクリプト

既存の demo/ 配下のページを chat_artifact テーブルに登録する。
プロジェクト/メッセージIDは空のままでも保持できるため、まずは
「全体で利用可能な成果物カタログ」として機能する。
"""
import sys
sys.path.insert(0, "D:/done")

from app.services.supabase_client import get_supabase_client


SAMPLES = [
    {
        "slug": "amagasaki-sales-dashboard",
        "kind": "demo",
        "label": "尼崎AI営業ダッシュボード",
        "preview_url": "/demo/amagasaki-sales-dashboard",
    },
]


OWNER_USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"


def seed():
    sb = get_supabase_client().client
    user_id = OWNER_USER_ID

    for sample in SAMPLES:
        existing = (
            sb.table("chat_artifact")
            .select("id")
            .eq("slug", sample["slug"])
            .eq("created_by", user_id)
            .execute()
        )
        if existing.data:
            print(f"  スキップ (既存): {sample['slug']}")
            continue

        result = sb.table("chat_artifact").insert({
            **sample,
            "created_by": user_id,
        }).execute()
        if result.data:
            print(f"  作成: {result.data[0].get('slug')} -> {result.data[0].get('id')}")
        else:
            print(f"  失敗: {sample['slug']}")

    print(f"サンプル {len(SAMPLES)} 件を処理しました")


if __name__ == "__main__":
    seed()
