"""
AIX事業ダッシュボードのシードデータ投入スクリプト。
クライアント（吉川特装＋仮想2社）と関連データを投入する。
"""
import sys

sys.path.insert(0, "D:/done")

from app.services.supabase_client import get_supabase_client


def get_owner_user_id(sb) -> str:
    """public.users から取得（aix_* は public.users にFK）。みきさん優先。"""
    target_email = "0aw325171@gmail.com"
    r = sb.table("users").select("id, email").eq("email", target_email).limit(1).execute()
    if r.data:
        return r.data[0]["id"]
    fb = sb.table("users").select("id").limit(1).execute()
    if fb.data:
        return fb.data[0]["id"]
    raise RuntimeError("public.users にユーザーがいません")


def seed():
    sb = get_supabase_client().client
    user_id = get_owner_user_id(sb)
    print(f"owner user_id={user_id}")

    for t in ("aix_tasks", "aix_engagements", "aix_contracts", "aix_activities",
              "aix_proposals", "aix_hypotheses", "aix_clients"):
        sb.table(t).delete().eq("created_by", user_id).execute()
    print("cleared previous rows")

    clients_payload = [
        {
            "name": "有限会社 吉川特装自動車",
            "industry": "自動車整備（特装車）",
            "region": "鳥取県米子市",
            "size": "small",
            "contact_name": "細田 かおり",
            "contact_role": "代表取締役",
            "contact_phone": "0859-27-4885",
            "stage": "live",
            "health_score": 85,
            "estimated_value": 500000,
            "notes": "新明和工業の認定修理工場。HP制作とWeb問い合わせフォームを提供中。LINE公式・修理進捗トラッキングが次フェーズ候補。",
            "tags": ["特装車", "新明和認定", "山陰", "DX初期"],
            "created_by": user_id,
        },
        {
            "name": "山陰物流 株式会社（仮名）",
            "industry": "運送・物流",
            "region": "島根県松江市",
            "size": "medium",
            "stage": "research",
            "health_score": 50,
            "notes": "配送ルート最適化とドライバー勤怠管理に課題。中国地方の物流DX候補。",
            "tags": ["物流", "勤怠DX", "ルート最適化"],
            "created_by": user_id,
        },
        {
            "name": "鳥取建設 株式会社（仮名）",
            "industry": "建設業",
            "region": "鳥取県鳥取市",
            "size": "medium",
            "stage": "proposal",
            "health_score": 60,
            "notes": "紙の工事日報をデジタル化したい。現場写真の共有とクラウド化が当面のニーズ。",
            "tags": ["建設", "日報DX", "現場DX"],
            "created_by": user_id,
        },
    ]
    res = sb.table("aix_clients").insert(clients_payload).execute()
    clients = {row["name"][:8]: row["id"] for row in res.data}
    yk_id = next(v for k, v in clients.items() if "吉川" in k)
    sl_id = next(v for k, v in clients.items() if "山陰" in k)
    tk_id = next(v for k, v in clients.items() if "鳥取建" in k)
    print(f"inserted {len(res.data)} clients")

    sb.table("aix_hypotheses").insert([
        {"client_id": yk_id, "title": "Web問い合わせフォームで電話対応を削減できる",
         "pain_point": "問い合わせの度に車台番号や型式を電話で説明している。ベテランの時間を奪っている。",
         "proposed_solution": "車台番号などを先に入力させるマルチステップフォーム。LINE画像送信フローをWebに統合。",
         "confidence": 90, "status": "validated", "created_by": user_id},
        {"client_id": yk_id, "title": "修理進捗の顧客可視化で問い合わせ電話を減らせる",
         "pain_point": "「うちの車、いつ直る？」の電話が毎日入る。社内でも進捗が見えていない。",
         "proposed_solution": "受付→部品手配→整備→完了 の進捗ステータスを顧客に共有できる簡易トラッキングページ。",
         "confidence": 65, "status": "draft", "created_by": user_id},
        {"client_id": yk_id, "title": "車検証OCRで部品照会を自動化できる",
         "pain_point": "新明和の部品DBに車台番号を手入力で照会している。時間と入力ミスが発生。",
         "proposed_solution": "車検証OCR + 過去履歴DBで車両情報を自動補完。新明和ポータルにワンクリック転記。",
         "confidence": 55, "status": "draft", "created_by": user_id},
        {"client_id": tk_id, "title": "現場写真+位置情報で日報を3分で完成できる",
         "pain_point": "手書き日報を事務所に戻って転記。現場終了後1時間の残業が常態化。",
         "proposed_solution": "スマホで写真と位置情報を自動紐付け。テンプレで事実ベースを埋めてAIがコメント提案。",
         "confidence": 70, "status": "validated", "created_by": user_id},
        {"client_id": sl_id, "title": "ルート最適化で1便あたり30分短縮できる",
         "pain_point": "配送順がドライバー経験頼り。新人は迷う時間が1時間/日発生。",
         "proposed_solution": "Google OR-Tools等で巡回最適化、日次配送計画を自動生成。",
         "confidence": 60, "status": "draft", "created_by": user_id},
    ]).execute()

    sb.table("aix_proposals").insert([
        {"client_id": yk_id, "title": "吉川特装 HP + スマート問い合わせフォーム",
         "summary": "認定修理工場としての信頼性訴求と、車両情報・画像をまとめて送信するマルチステップ問い合わせフォーム。",
         "prototype_url": "https://kittoku.vercel.app",
         "status": "won", "estimated_value": 200000,
         "sent_at": "2026-04-22T10:00:00+09:00", "created_by": user_id},
        {"client_id": yk_id, "title": "修理進捗トラッキングページ",
         "summary": "受付番号で顧客が自車の修理進捗を確認できる。担当者の更新は1秒で済む設計。",
         "status": "draft", "created_by": user_id},
        {"client_id": tk_id, "title": "建設現場 日報アプリ MVP",
         "summary": "スマホで現場写真と位置情報を記録するだけで日報が自動生成。PWA想定。",
         "status": "sent", "sent_at": "2026-04-22T15:00:00+09:00", "created_by": user_id},
    ]).execute()

    sb.table("aix_activities").insert([
        {"client_id": yk_id, "activity_type": "call",
         "subject": "HP制作の相談", "body": "電話問い合わせの負担軽減を相談。LINE問い合わせフローの課題共有。",
         "occurred_at": "2026-04-20T14:00:00+09:00", "created_by": user_id},
        {"client_id": yk_id, "activity_type": "email_sent",
         "subject": "HPプロトタイプ完成のご報告", "body": "デモ版HPをお送りします。修正点があればご連絡ください。",
         "occurred_at": "2026-04-24T09:00:00+09:00", "created_by": user_id},
        {"client_id": yk_id, "activity_type": "meeting",
         "subject": "HPフィードバックMTG（オンライン・45分）",
         "body": "HPプロトへのフィードバックと、次フェーズ（修理進捗トラッキング）の優先順位確認。",
         "occurred_at": "2026-04-26T10:00:00+09:00",
         "next_action": "進捗トラッキングのMVP仕様作成",
         "next_action_at": "2026-05-02T17:00:00+09:00", "created_by": user_id},
        {"client_id": tk_id, "activity_type": "email_sent",
         "subject": "建設日報アプリMVPのご提案",
         "body": "3分で日報が完成するMVPのデモ動画を添付しました。",
         "occurred_at": "2026-04-22T16:00:00+09:00", "created_by": user_id},
    ]).execute()

    sb.table("aix_contracts").insert([
        {"client_id": yk_id, "title": "HP制作 + 運用サポート",
         "contract_type": "subscription", "initial_value": 200000, "monthly_value": 30000,
         "start_date": "2026-04-24", "status": "active",
         "notes": "HP本体 + 月次微修正 + 問い合わせフォーム改善運用",
         "created_by": user_id},
    ]).execute()

    sb.table("aix_engagements").insert([
        {"client_id": yk_id, "deliverable_name": "吉川特装 公式HP",
         "deliverable_type": "website", "deliverable_url": "https://kittoku.vercel.app",
         "repo_path": "frontend/src/app/artifacts/kittoku",
         "status": "live", "health_score": 90,
         "kpis": {"pages": 5, "videos": 1, "vehicles": 9},
         "notes": "新明和認定バッジ + 9車種ロゴ + 3シーン構成ヒーロー動画",
         "created_by": user_id},
    ]).execute()

    sb.table("aix_tasks").insert([
        {"client_id": yk_id, "title": "実会社情報をHPに反映",
         "description": "代表挨拶・スタッフ写真・実績事例を吉川さん本人版に差し替え。",
         "zone": "green", "status": "todo", "priority": "high",
         "due_at": "2026-05-01T17:00:00+09:00", "created_by": user_id},
        {"client_id": yk_id, "title": "Web問い合わせ運用の効果計測",
         "description": "1週間分の問い合わせが電話/Webのどちらで入ったか集計。",
         "zone": "green", "status": "in_progress", "priority": "high",
         "due_at": "2026-05-05T17:00:00+09:00", "created_by": user_id},
        {"client_id": yk_id, "title": "問い合わせ完了画面にLINE QR追加",
         "description": "画像送付の補完導線として LINE QR コードを表示。",
         "zone": "green", "status": "awaiting_approval", "priority": "normal",
         "created_by": user_id},
        {"client_id": yk_id, "title": "HP完成のご報告メール ドラフト",
         "description": "吉川さん向けの完成報告メールの文面を生成。送信前にレビュー必要。",
         "zone": "yellow", "status": "awaiting_approval", "priority": "normal",
         "requested_action": "メール文面の承認＆送信", "created_by": user_id},
        {"client_id": yk_id, "title": "新仮説提案: 部品OCR自動化",
         "description": "車検証のOCRで車台番号を自動抽出し、発注ミス削減する新仮説。",
         "zone": "green", "status": "awaiting_approval", "priority": "normal",
         "requested_action": "仮説リストへ追加 or 却下", "created_by": user_id},
        {"client_id": tk_id, "title": "リマインド営業メール ドラフト",
         "description": "開封済みだが返信なし。3日後に軽いリマインドを送るドラフト。",
         "zone": "yellow", "status": "awaiting_approval", "priority": "normal",
         "requested_action": "送信タイミングの承認", "created_by": user_id},
        {"client_id": sl_id, "title": "山陰物流の課題分析レポート",
         "description": "公開情報から仮説候補3件を抽出。コールドメール送付前の前提整理。",
         "zone": "green", "status": "done", "priority": "normal",
         "result_summary": "ルート最適化・勤怠管理・荷主交渉の3軸で仮説まとめ",
         "completed_at": "2026-04-23T19:00:00+09:00", "created_by": user_id},
        {"client_id": yk_id, "title": "吉川特装HP 初稿の構築",
         "description": "新明和風ネイビー+黄色アクセント。マルチステップ問い合わせフォーム実装。",
         "zone": "green", "status": "done", "priority": "high",
         "result_summary": "5ページ + ヒーロー動画 + 問い合わせフォームをデプロイ",
         "artifact_urls": ["https://kittoku.vercel.app"],
         "completed_at": "2026-04-27T18:00:00+09:00", "created_by": user_id},
    ]).execute()

    print("\n=== inserted ===")
    for t in ("aix_clients", "aix_hypotheses", "aix_proposals", "aix_activities",
              "aix_contracts", "aix_engagements", "aix_tasks"):
        c = sb.table(t).select("id", count="exact").eq("created_by", user_id).execute()
        print(f"  {t}: {c.count}")


if __name__ == "__main__":
    seed()
