"""ダン用Notion: サンプルデータ + プリセットトリガー投入スクリプト

実行前提: マイグレーション 036_dan_notion.sql が適用済みであること。

投入内容:
  1. ルートページ 4枚 (受信箱 / 経理 / プロジェクト / 議事録)
  2. 各ページ配下に サンプルブロック
  3. プリセットトリガー 3件 (Gmail決算資料 / 請求書期限通知 / 税理士送付提案)
  4. サンプル通知 2件
"""
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "D:/done")

from app.services.supabase_client import get_supabase_client
from app.utils.fractional_index import generate_n_keys_between

OWNER_USER_ID = "1f53bb2a-51da-4a2a-be9e-4c5a0f74d5f1"  # dan-test@example.com


def seed():
    sb = get_supabase_client().client
    user_id = OWNER_USER_ID

    print(f"=== ダン用Notion サンプルデータ投入: user={user_id} ===\n")

    # ============================================================
    # 1. ルートページ
    # ============================================================
    pages_def = [
        {"title": "📥 受信箱", "icon": "📥",
         "desc": "Gmail/コラボから自動収集された未整理の情報"},
        {"title": "💰 経理", "icon": "💰",
         "desc": "請求書・領収書・決算資料"},
        {"title": "🚀 プロジェクト", "icon": "🚀",
         "desc": "進行中のプロジェクト全般"},
        {"title": "📝 議事録", "icon": "📝",
         "desc": "会議メモ・打ち合わせ記録"},
    ]
    keys = generate_n_keys_between(None, None, len(pages_def))
    page_ids = []
    for p, k in zip(pages_def, keys):
        row = {
            "user_id": user_id,
            "type": "page",
            "order_key": k,
            "properties": {"title": p["title"]},
            "content": [{"type": "text", "text": p["desc"]}],
            "icon": p["icon"],
            "tags": ["seed"],
        }
        res = sb.table("blocks").insert(row).execute()
        if res.data:
            page_ids.append(res.data[0]["id"])
            print(f"  ページ作成: {p['title']}")

    if len(page_ids) < 4:
        print("ページ作成に失敗しました")
        return

    inbox_id, accounting_id, project_id, minutes_id = page_ids

    # ============================================================
    # 2. ブロック (各ページ配下)
    # ============================================================
    sample_blocks = [
        # 受信箱
        (inbox_id, "heading", {}, [{"type": "text", "text": "今日の自動収集"}]),
        (inbox_id, "paragraph", {},
         [{"type": "text", "text": "Autopilot が Gmail と コラボから取得した項目がここに並びます。"}]),
        (inbox_id, "checklist", {"checked": False},
         [{"type": "text", "text": "請求書 (吉川特装) を確認"}]),
        (inbox_id, "checklist", {"checked": True},
         [{"type": "text", "text": "Kim税理士からの返信を確認"}]),
        # 経理
        (accounting_id, "heading", {}, [{"type": "text", "text": "今月の請求書"}]),
        (accounting_id, "callout", {"emoji": "⚠️"},
         [{"type": "text", "text": "支払い期限の3日前に Autopilot が自動通知します"}]),
        (accounting_id, "invoice", {"amount": 132000, "due": "2026-04-25", "vendor": "AWS"},
         [{"type": "text", "text": "AWS 月額利用料 ¥132,000 (期限 2026-04-25)"}]),
        # プロジェクト
        (project_id, "heading", {}, [{"type": "text", "text": "進行中のクライアント"}]),
        (project_id, "bullet_list", {}, [{"type": "text", "text": "吉川特装 HP制作 (デプロイ済)"}]),
        (project_id, "bullet_list", {}, [{"type": "text", "text": "五条運輸 ロゴ刷新"}]),
        (project_id, "bullet_list", {}, [{"type": "text", "text": "バードSTC 提案動画"}]),
        # 議事録
        (minutes_id, "heading", {}, [{"type": "text", "text": "2026-04-10 Kim税理士 月次MTG"}]),
        (minutes_id, "paragraph", {},
         [{"type": "text", "text": "決算資料の提出期限は4月末。前年同月比+15%を維持。"}]),
    ]

    parent_groups: dict[str, list] = {}
    for parent, *_ in sample_blocks:
        parent_groups.setdefault(parent, []).append(None)

    parent_keys: dict[str, list[str]] = {
        p: generate_n_keys_between(None, None, len(v))
        for p, v in parent_groups.items()
    }
    parent_idx: dict[str, int] = {p: 0 for p in parent_keys}

    for parent_id, btype, props, content in sample_blocks:
        idx = parent_idx[parent_id]
        order_key = parent_keys[parent_id][idx]
        parent_idx[parent_id] += 1
        sb.table("blocks").insert({
            "user_id": user_id,
            "parent_id": parent_id,
            "type": btype,
            "order_key": order_key,
            "properties": props,
            "content": content,
            "tags": ["seed"],
        }).execute()
    print(f"  サンプルブロック {len(sample_blocks)} 件投入")

    # ============================================================
    # 3. プリセットトリガー
    # ============================================================
    presets = [
        {
            "name": "Gmail決算資料 自動整理",
            "description": "決算/会計関連メールを 経理 ページ配下に自動分類する",
            "kind": "gmail",
            "config": {"query": "from:kim", "table": "gmail_messages"},
            "logic": {"classify": True, "target_page_id": accounting_id},
            "actions": [
                {"type": "classify", "categories": ["決算", "請求書", "領収書", "その他"]},
                {"type": "create_block", "block_type": "email", "parent_id": accounting_id},
                {"type": "notify", "title": "Kim税理士から新着メールあり"},
            ],
            "is_enabled": True,
        },
        {
            "name": "請求書 期限3日前 通知",
            "description": "blocks.type='invoice' の properties.due の3日前に通知センターへ alert",
            "kind": "cron",
            "config": {"interval_seconds": 3600},
            "logic": {"days_before": 3},
            "actions": [
                {"type": "scan_blocks", "block_type": "invoice", "field": "properties.due"},
                {"type": "notify", "title": "支払期限が近づいています", "severity": "warning"},
            ],
            "is_enabled": True,
        },
        {
            "name": "税理士への資料送付 提案",
            "description": "毎月25日に当月の経理ブロックをまとめ、Kim税理士宛てメール下書きを提案",
            "kind": "cron",
            "config": {"interval_seconds": 86400},
            "logic": {"day_of_month": 25, "recipient": "kim@example.com"},
            "actions": [
                {"type": "collect_blocks", "parent_id": accounting_id, "month": "current"},
                {"type": "draft_email", "to": "kim@example.com",
                 "subject": "今月の経理資料"},
                {"type": "notify", "title": "税理士向けメール下書きを作成しました",
                 "severity": "info"},
            ],
            "is_enabled": False,
        },
    ]
    for t in presets:
        res = sb.table("triggers").insert({"user_id": user_id, **t}).execute()
        if res.data:
            print(f"  トリガー作成: {t['name']}")

    # ============================================================
    # 4. サンプル通知
    # ============================================================
    notifications = [
        {
            "user_id": user_id,
            "kind": "invoice_due",
            "title": "AWS の支払期限が3日後",
            "body": "¥132,000 — 経理ページに詳細あり",
            "severity": "warning",
            "due_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        },
        {
            "user_id": user_id,
            "kind": "autopilot_completed",
            "title": "Kim税理士からのメールを 経理 に整理しました",
            "body": "3件のメールを自動分類しました",
            "severity": "info",
        },
    ]
    for n in notifications:
        sb.table("dan_notifications").insert(n).execute()
    print(f"  通知 {len(notifications)} 件投入")

    print("\n=== 投入完了 ===")
    print(f"  ページ:     {len(page_ids)}")
    print(f"  ブロック:   {len(sample_blocks)}")
    print(f"  トリガー:   {len(presets)}")
    print(f"  通知:       {len(notifications)}")
    print("\n  ブラウザで http://localhost:3000/dan-notion を開いてください")


if __name__ == "__main__":
    seed()
