"""停止済み Observer が残した stale な observation 通知を expired にして通知タブから片付ける。

- ハード削除はしない（status を 'expired' に更新するので後から復元可能）。
- 対象は status='pending' かつ type='observation' のみ。要対応提案(reply/action)は触らない。
- --dry-run で件数だけ確認、--apply で実行。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.supabase_client import get_supabase_client


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="実際に更新する（既定は dry-run）")
    args = ap.parse_args()

    sb = get_supabase_client().client

    target = (
        sb.table("dan_proposals")
        .select("id", count="exact")
        .eq("status", "pending")
        .eq("type", "observation")
        .execute()
    )
    n = target.count or 0
    print(f"対象(pending かつ observation): {n} 件")

    if not args.apply:
        print("[dry-run] --apply を付けると expired に更新します。")
        return

    if n == 0:
        print("対象なし。終了。")
        return

    res = (
        sb.table("dan_proposals")
        .update({"status": "expired"})
        .eq("status", "pending")
        .eq("type", "observation")
        .execute()
    )
    updated = len(res.data or [])
    print(f"[applied] {updated} 件を expired に更新しました。")

    remaining = (
        sb.table("dan_proposals")
        .select("id", count="exact")
        .eq("status", "pending")
        .execute()
        .count
        or 0
    )
    print(f"残り pending: {remaining} 件")


if __name__ == "__main__":
    main()
