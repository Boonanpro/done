"""dan_proposals の種別×ステータス内訳を実測する診断スクリプト（読み取り専用）。

通知タブ整理(Phase 0)の前に、何を消すと安全かを把握するために使う。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.supabase_client import get_supabase_client


def count(sb, **filters):
    q = sb.table("dan_proposals").select("id", count="exact")
    for k, v in filters.items():
        q = q.eq(k, v)
    return q.execute().count or 0


def main():
    sb = get_supabase_client().client

    total = count(sb)
    print(f"総数: {total}")

    # ステータス別
    print("\n--- status 別 ---")
    for st in ["pending", "approved", "rejected", "expired"]:
        print(f"  {st:10s}: {count(sb, status=st)}")

    # 種別を列挙（pending のみ・サンプル取得して type を集計）
    print("\n--- pending の type 別 ---")
    rows = sb.table("dan_proposals").select("type").eq("status", "pending").limit(2000).execute().data or []
    from collections import Counter
    c = Counter((r.get("type") or "(null)") for r in rows)
    for t, n in c.most_common():
        print(f"  {t:15s}: {n}")

    # 直近の pending を数件サンプル表示
    print("\n--- pending サンプル(最新5件) ---")
    sample = (
        sb.table("dan_proposals")
        .select("type,title,created_at")
        .eq("status", "pending")
        .order("created_at", desc=True)
        .limit(5)
        .execute()
        .data
        or []
    )
    for r in sample:
        print(f"  [{r.get('type')}] {r.get('title')} ({r.get('created_at')})")


if __name__ == "__main__":
    main()
